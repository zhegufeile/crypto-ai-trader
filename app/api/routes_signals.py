from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.storage.db import get_session
from app.storage.repositories import SignalRepository

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def list_signals(limit: int = 50, session: Session = Depends(get_session)) -> list[dict]:
    records = SignalRepository(session).list_signals(limit)
    return [record.model_dump() for record in records]
