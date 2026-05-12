from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.config import Settings, get_settings
from app.core.scheduler import run_scan_once
from app.storage.db import get_session

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/scan")
async def scan_once(
    tier_mode: str | None = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    result = await run_scan_once(session=session, settings=settings, strategy_tier_mode=tier_mode)
    return result
