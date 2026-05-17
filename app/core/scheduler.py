import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session

from app.config import Settings, get_settings
from app.core.execution_engine import ExecutionEngine
from app.core.simulator import SimulatedTrade
from app.core.signal_engine import SignalEngine
from app.data.market_collector import MarketCollector
from app.data.schema import MarketSnapshot
from app.storage.db import engine
from app.storage.repositories import SignalRepository, TradeFeeRepository, TradeJournalRepository, TradeRepository

logger = logging.getLogger(__name__)


async def run_scan_once(
    session: Session | None = None,
    settings: Settings | None = None,
    strategy_tier_mode: str | None = None,
) -> dict:
    settings = settings or get_settings()
    collector = MarketCollector(settings=settings)
    signal_engine = SignalEngine(settings=settings)
    execution_engine = ExecutionEngine(settings=settings)
    effective_tier_mode = strategy_tier_mode or settings.signal_strategy_tier_mode

    owns_session = session is None
    if session is None:
        session = Session(engine)

    try:
        trade_repo = TradeRepository(session)
        signal_repo = SignalRepository(session)
        journal_repo = TradeJournalRepository(session)
        fee_repo = TradeFeeRepository(session)
        try:
            candidates = await collector.collect_candidates()
        except Exception as exc:
            logger.exception("market scan failed while collecting candidates")
            journal_repo.log_event(
                symbol="SYSTEM",
                trade_id=None,
                event_type="scan_failed",
                status="warning",
                message="market scan failed while collecting candidates",
                details={
                    "error": str(exc),
                    "stage": "collect_candidates",
                    "tier_mode": effective_tier_mode,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            return {
                "candidates": 0,
                "signals": 0,
                "simulated_trades": 0,
                "managed_positions": 0,
                "strategy_tier_mode": effective_tier_mode,
                "circuit_breaker": False,
                "status": "error",
                "error": str(exc),
                "stage": "collect_candidates",
            }
        candidate_map = {candidate.snapshot.symbol: candidate.snapshot for candidate in candidates}
        managed_trades = []
        state_changes = 0
        open_trades = trade_repo.list_open_trades()
        for trade in open_trades:
            if trade.status == "pending_entry":
                claimed_trade = trade_repo.claim_pending_entry(trade.id)
                if claimed_trade is None:
                    continue
                trade = claimed_trade
            before = trade.model_copy(deep=True)
            snapshot = candidate_map.get(trade.symbol)
            if snapshot is None:
                snapshot = _fallback_snapshot_for_trade(trade)
            try:
                managed_trade = execution_engine.manage_simulated(trade, snapshot)
            except Exception as exc:
                if getattr(exc, "context", None) is not None:
                    logger.warning("trade management failed: %s", exc)
                else:
                    logger.exception("trade management failed")
                failed_trade = getattr(exc, "trade", None)
                if failed_trade is not None:
                    trade_repo.update_trade(failed_trade)
                    _log_fee_delta(before, failed_trade, fee_repo)
                    _log_trade_transition_events(journal_repo, before, failed_trade)
                journal_repo.log_event(
                    symbol=trade.symbol,
                    trade_id=trade.id,
                    event_type="trade_manage_failed",
                    status="error",
                    message="trade management failed",
                    details={
                        "error": str(exc),
                        "status": trade.status,
                        "tier_mode": effective_tier_mode,
                        "error_context": getattr(exc, "context", {}),
                    },
                )
                continue
            trade_repo.update_trade(managed_trade)
            managed_trades.append(managed_trade)
            _log_fee_delta(before, managed_trade, fee_repo)
            for event_type in _log_trade_transition_events(journal_repo, before, managed_trade):
                state_changes += 1
        active_trades = trade_repo.list_open_trades()
        recent_closed_trades = trade_repo.list_recent_closed_trades()
        open_positions = len([trade for trade in active_trades if trade.is_active])
        recent_trade_actions = journal_repo.count_recent_actions(
            settings.trade_action_circuit_window_minutes,
            event_types=[
                "trade_opened",
                "trade_closed",
                "trade_cancelled",
                "trade_confirmed",
                "trade_force_closed",
                "trade_execution_failed",
                "trade_manage_failed",
            ],
        )
        if recent_trade_actions >= settings.max_trade_actions_in_window or state_changes >= settings.max_trade_state_changes_per_scan:
            journal_repo.log_event(
                symbol="SYSTEM",
                trade_id=None,
                event_type="trade_loop_circuit_breaker",
                status="warning",
                message="trade loop circuit breaker blocked new entries",
                details={
                    "recent_trade_actions": recent_trade_actions,
                    "state_changes_this_scan": state_changes,
                    "window_minutes": settings.trade_action_circuit_window_minutes,
                },
            )
            return {
                "candidates": len(candidates),
                "signals": 0,
                "simulated_trades": 0,
                "managed_positions": len(managed_trades),
                "strategy_tier_mode": effective_tier_mode,
                "circuit_breaker": True,
            }
        signals = signal_engine.generate_signals(
            candidates,
            open_positions=open_positions,
            strategy_tier_mode=effective_tier_mode,
            active_trades=active_trades,
            recent_closed_trades=recent_closed_trades,
        )
        trades = []
        for signal in signals:
            current_active_trades = active_trades + trades
            if any(trade.symbol == signal.symbol and trade.is_active for trade in current_active_trades):
                journal_repo.log_event(
                    symbol=signal.symbol,
                    trade_id=None,
                    event_type="trade_blocked",
                    status="warning",
                    message="symbol already has an active or pending position",
                    details={
                        "reasons": ["symbol already has an active or pending position"],
                        "tier_mode": effective_tier_mode,
                        "primary_strategy_name": signal.primary_strategy_name,
                        "matched_strategy_names": signal.matched_strategy_names,
                    },
                )
                continue
            if journal_repo.has_recent_symbol_event(
                signal.symbol,
                settings.trade_action_circuit_window_minutes,
                event_types=["trade_force_closed", "trade_execution_failed", "trade_manage_failed"],
            ):
                journal_repo.log_event(
                    symbol=signal.symbol,
                    trade_id=None,
                    event_type="trade_blocked",
                    status="warning",
                    message="recent symbol activity blocked immediate re-entry",
                    details={
                        "reasons": ["symbol had recent execution activity; waiting for cool-off window"],
                        "tier_mode": effective_tier_mode,
                        "primary_strategy_name": signal.primary_strategy_name,
                        "matched_strategy_names": signal.matched_strategy_names,
                    },
                )
                continue
            signal_repo.save_signal(signal)
            candidate = next(item for item in candidates if item.snapshot.symbol == signal.symbol)
            analysis = signal_engine.analyst.analyze(candidate)
            risk_decision = signal_engine.risk_manager.evaluate(
                candidate,
                analysis,
                open_positions=open_positions + len(trades),
                active_trades=current_active_trades,
                recent_closed_trades=recent_closed_trades,
            )
            try:
                trade = execution_engine.execute_simulated(signal, risk_decision)
            except Exception as exc:
                if getattr(exc, "context", None) is not None:
                    logger.warning("trade execution failed: %s", exc)
                else:
                    logger.exception("trade execution failed")
                failed_trade = getattr(exc, "trade", None)
                if failed_trade is not None:
                    saved_trade = trade_repo.save_trade(failed_trade)
                    _log_fee_delta(None, saved_trade, fee_repo)
                    journal_repo.log_event(
                        symbol=saved_trade.symbol,
                        trade_id=saved_trade.id,
                        event_type="trade_force_closed",
                        status="warning",
                        message=saved_trade.exit_reason or "trade was force-closed after execution failure",
                    details={
                        "direction": saved_trade.direction,
                        "structure": saved_trade.structure,
                        "entry_mode": saved_trade.entry_mode,
                        "entry": saved_trade.entry,
                        "quantity": saved_trade.quantity,
                        "notional_usdt": saved_trade.notional_usdt,
                        "stop_loss": saved_trade.stop_loss,
                        "take_profit": saved_trade.take_profit,
                        "tier_mode": effective_tier_mode,
                        "execution_mode": "simulation" if settings.use_simulation else "live",
                        "primary_strategy_name": saved_trade.primary_strategy_name,
                        "matched_strategy_names": saved_trade.matched_strategy_names,
                    },
                )
                journal_repo.log_event(
                    symbol=signal.symbol,
                    trade_id=None,
                    event_type="trade_execution_failed",
                    status="error",
                    message="trade execution failed",
                    details={
                        "error": str(exc),
                        "tier_mode": effective_tier_mode,
                        "reasons": risk_decision.reasons,
                        "error_context": getattr(exc, "context", {}),
                        "primary_strategy_name": signal.primary_strategy_name,
                        "matched_strategy_names": signal.matched_strategy_names,
                    },
                )
                continue
            if trade:
                saved_trade = trade_repo.save_trade(trade)
                trades.append(saved_trade)
                _log_fee_delta(None, saved_trade, fee_repo)
                journal_repo.log_event(
                    symbol=saved_trade.symbol,
                    trade_id=saved_trade.id,
                    event_type="trade_opened",
                    message="trade opened",
                    details={
                        "direction": saved_trade.direction,
                        "structure": saved_trade.structure,
                        "entry_mode": saved_trade.entry_mode,
                        "entry": saved_trade.entry,
                        "quantity": saved_trade.quantity,
                        "notional_usdt": saved_trade.notional_usdt,
                        "stop_loss": saved_trade.stop_loss,
                        "take_profit": saved_trade.take_profit,
                        "tier_mode": effective_tier_mode,
                        "execution_mode": "simulation" if settings.use_simulation else "live",
                        "primary_strategy_name": saved_trade.primary_strategy_name,
                        "matched_strategy_names": saved_trade.matched_strategy_names,
                    },
                )
            else:
                journal_repo.log_event(
                    symbol=signal.symbol,
                    trade_id=None,
                    event_type="trade_blocked",
                    status="warning",
                    message="risk manager blocked trade execution",
                    details={
                        "reasons": risk_decision.reasons,
                        "tier_mode": effective_tier_mode,
                    },
                )
        return {
            "candidates": len(candidates),
            "signals": len(signals),
            "simulated_trades": len(trades),
            "managed_positions": len(managed_trades),
            "strategy_tier_mode": effective_tier_mode,
            "circuit_breaker": False,
        }
    finally:
        if owns_session:
            session.close()


def _fallback_snapshot_for_trade(trade: SimulatedTrade) -> MarketSnapshot:
    reference_price = trade.last_price or trade.entry
    return MarketSnapshot(
        symbol=trade.symbol,
        price=reference_price,
        quote_volume_24h=0,
        volume_24h=0,
        source="live_trade_fallback",
    )


def build_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    settings = settings or get_settings()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scan_once,
        "interval",
        seconds=settings.scan_interval_seconds,
        id="market_scan",
        max_instances=1,
        coalesce=True,
        kwargs={"settings": settings},
    )
    return scheduler


def _journal_events_for_trade_transition(before: SimulatedTrade, after: SimulatedTrade) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    if before.status in {"pending_entry", "entry_in_progress"} and after.status == "open" and after.entry_confirmed:
        events.append(("trade_confirmed", "pending entry confirmed and trade is now live"))
    if not before.tp1_hit and after.tp1_hit:
        events.append(("trade_tp1_hit", "first take-profit step was hit"))
    if not before.tp2_hit and after.tp2_hit:
        events.append(("trade_tp2_hit", "second take-profit step was hit"))
    if before.status != after.status and after.status == "closed":
        events.append(("trade_closed", after.exit_reason or "trade closed"))
    if before.status != after.status and after.status == "cancelled":
        events.append(("trade_cancelled", after.exit_reason or "trade cancelled"))
    return events


def _log_trade_transition_events(
    journal_repo: TradeJournalRepository,
    before: SimulatedTrade,
    after: SimulatedTrade,
) -> list[str]:
    logged_events: list[str] = []
    for event_type, message in _journal_events_for_trade_transition(before, after):
        if event_type == "trade_confirmed" and journal_repo.has_trade_event(after.id, event_type):
            continue
        journal_repo.log_event(
            symbol=after.symbol,
            trade_id=after.id,
            event_type=event_type,
            message=message,
            details={
                "status": after.status,
                "entry_mode": after.entry_mode,
                "realized_pnl_usdt": after.realized_pnl_usdt,
                "exit_reason": after.exit_reason,
            },
        )
        logged_events.append(event_type)
    return logged_events


def _log_fee_delta(before: SimulatedTrade | None, after: SimulatedTrade, fee_repo: TradeFeeRepository) -> None:
    previous = before.fees_paid_usdt if before is not None else 0.0
    delta = round((after.fees_paid_usdt or 0.0) - (previous or 0.0), 6)
    if delta <= 0:
        return
    fee_repo.log_fee(
        trade_id=after.id,
        symbol=after.symbol,
        event_type=_fee_event_type(before, after),
        amount_usdt=delta,
    )


def _fee_event_type(before: SimulatedTrade | None, after: SimulatedTrade) -> str:
    if before is None:
        return "entry_fee"
    if before.status in {"pending_entry", "entry_in_progress"} and after.status == "open":
        return "entry_fee"
    if not before.tp1_hit and after.tp1_hit:
        return "tp1_exit_fee"
    if not before.tp2_hit and after.tp2_hit:
        return "tp2_exit_fee"
    if before.status != after.status and after.status == "closed":
        return "final_exit_fee"
    return "trade_fee"
