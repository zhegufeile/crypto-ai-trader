import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session

from app.config import Settings, get_settings
from app.core.execution_engine import ExecutionEngine
from app.core.simulator import SimulatedTrade
from app.core.signal_engine import SignalEngine
from app.data.market_collector import MarketCollector
from app.storage.db import engine
from app.storage.repositories import SignalRepository, TradeJournalRepository, TradeRepository

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
            before = trade.model_copy(deep=True)
            snapshot = candidate_map.get(trade.symbol)
            if snapshot is None:
                continue
            managed_trade = execution_engine.manage_simulated(trade, snapshot)
            trade_repo.update_trade(managed_trade)
            managed_trades.append(managed_trade)
            for event_type, message in _journal_events_for_trade_transition(before, managed_trade):
                journal_repo.log_event(
                    symbol=managed_trade.symbol,
                    trade_id=managed_trade.id,
                    event_type=event_type,
                    message=message,
                    details={
                        "status": managed_trade.status,
                        "entry_mode": managed_trade.entry_mode,
                        "realized_pnl_usdt": managed_trade.realized_pnl_usdt,
                        "exit_reason": managed_trade.exit_reason,
                    },
                )
                state_changes += 1
        active_trades = trade_repo.list_open_trades()
        recent_closed_trades = trade_repo.list_recent_closed_trades()
        open_positions = len([trade for trade in active_trades if trade.is_active])
        recent_trade_actions = journal_repo.count_recent_actions(
            settings.trade_action_circuit_window_minutes,
            event_types=["trade_opened", "trade_closed", "trade_cancelled", "trade_confirmed"],
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
            signal_repo.save_signal(signal)
            current_active_trades = active_trades + trades
            candidate = next(item for item in candidates if item.snapshot.symbol == signal.symbol)
            analysis = signal_engine.analyst.analyze(candidate)
            risk_decision = signal_engine.risk_manager.evaluate(
                candidate,
                analysis,
                open_positions=open_positions + len(trades),
                active_trades=current_active_trades,
                recent_closed_trades=recent_closed_trades,
            )
            trade = execution_engine.execute_simulated(signal, risk_decision)
            if trade:
                saved_trade = trade_repo.save_trade(trade)
                trades.append(saved_trade)
                journal_repo.log_event(
                    symbol=saved_trade.symbol,
                    trade_id=saved_trade.id,
                    event_type="trade_opened",
                    message="simulated trade opened",
                    details={
                        "direction": saved_trade.direction,
                        "structure": saved_trade.structure,
                        "entry_mode": saved_trade.entry_mode,
                        "entry": saved_trade.entry,
                        "stop_loss": saved_trade.stop_loss,
                        "take_profit": saved_trade.take_profit,
                        "tier_mode": effective_tier_mode,
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
    if before.status == "pending_entry" and after.status == "open" and after.entry_confirmed:
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
