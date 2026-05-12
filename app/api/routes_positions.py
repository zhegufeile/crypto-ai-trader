from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.storage.db import get_session
from app.storage.repositories import SignalRepository, TradeJournalRepository, TradeRepository

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("")
def list_positions(include_closed: bool = False, session: Session = Depends(get_session)) -> list[dict]:
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
    }
    if clear_signals:
        result["signals_deleted"] = SignalRepository(session).delete_all()
    if clear_positions:
        result["positions_deleted"] = TradeRepository(session).delete_all()
    if clear_journal:
        result["journal_deleted"] = TradeJournalRepository(session).delete_all()
    result["status"] = "ok"
    return result
