from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.config import Settings, get_settings
from app.core.signal_engine import SignalEngine
from app.data.market_collector import MarketCollector
from app.data.schema import CandidateDiagnostic
from app.storage.db import get_session
from app.storage.repositories import TradeRepository

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/candidates")
async def list_candidate_diagnostics(
    limit: int = 10,
    tier_mode: str | None = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[CandidateDiagnostic]:
    collector = MarketCollector(settings=settings)
    engine = SignalEngine(settings=settings)
    open_positions = len(TradeRepository(session).list_open_trades())
    try:
        candidates = await collector.collect_candidates()
    except Exception:
        return []
    effective_tier_mode = tier_mode or settings.signal_strategy_tier_mode
    diagnostics = engine.diagnose_candidates(
        candidates,
        open_positions=open_positions,
        strategy_tier_mode=effective_tier_mode,
    )
    return diagnostics[:limit]
