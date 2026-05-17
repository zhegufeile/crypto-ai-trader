from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.config import get_settings
from app.core.live_trader import BinanceLiveTrader
from app.core.scheduler import _fallback_snapshot_for_trade, _log_fee_delta, _log_trade_transition_events
from app.storage.db import get_session
from app.storage.repositories import SignalRepository, TradeFeeRepository, TradeJournalRepository, TradeRepository

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("")
def list_positions(include_closed: bool = False, session: Session = Depends(get_session)) -> list[dict]:
    _reconcile_live_positions(session)
    repo = TradeRepository(session)
    records = repo.list_all_trades() if include_closed else repo.list_open_trades()
    return [record.model_dump() for record in records]


@router.get("/journal")
def list_trade_journal(limit: int = 100, session: Session = Depends(get_session)) -> list[dict]:
    repo = TradeJournalRepository(session)
    records = repo.list_events(limit=limit)
    return [record if isinstance(record, dict) else record.model_dump() for record in records]


@router.post("/reset")
def reset_simulation_runtime(
    clear_signals: bool = True,
    clear_positions: bool = True,
    clear_journal: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    result = {
        "signals_deleted": 0,
        "positions_deleted": 0,
        "journal_deleted": 0,
        "fees_deleted": 0,
    }
    if clear_signals:
        result["signals_deleted"] = SignalRepository(session).delete_all()
    if clear_positions:
        result["positions_deleted"] = TradeRepository(session).delete_all()
    if clear_journal:
        result["journal_deleted"] = TradeJournalRepository(session).delete_all()
        result["fees_deleted"] = TradeFeeRepository(session).delete_all()
    result["status"] = "ok"
    return result


def _reconcile_live_positions(session: Session) -> None:
    settings = get_settings()
    if settings.use_simulation or not settings.live_trading_enabled:
        return

    trade_repo = TradeRepository(session)
    journal_repo = TradeJournalRepository(session)
    fee_repo = TradeFeeRepository(session)
    live_trader = BinanceLiveTrader(settings=settings)

    for trade in trade_repo.list_open_trades():
        before = trade.model_copy(deep=True)
        snapshot = _fallback_snapshot_for_trade(trade)
        snapshot.timestamp = datetime.now(UTC)
        try:
            reconciled = live_trader.update_trade(trade, snapshot)
        except Exception as exc:
            journal_repo.log_event(
                symbol=trade.symbol,
                trade_id=trade.id,
                event_type="trade_manage_failed",
                status="error",
                message="trade management failed during position sync",
                details={
                    "error": str(exc),
                    "status": trade.status,
                    "error_context": getattr(exc, "context", {}),
                },
            )
            continue

        trade_repo.update_trade(reconciled)
        _log_fee_delta(before, reconciled, fee_repo)
        _log_trade_transition_events(journal_repo, before, reconciled)
