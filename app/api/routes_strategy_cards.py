from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.knowledge.strategy_store import StrategyStore
from app.knowledge.tiering import compute_strategy_tier
from app.storage.db import get_session
from app.storage.repositories import StrategyMetricRepository

router = APIRouter(prefix="/strategy-cards", tags=["strategy-cards"])


class StrategyCardStatsResponse(BaseModel):
    name: str
    description: str = ""
    market: str = "any"
    timeframe: str = "any"
    creator: str = "unknown"
    confidence_bias: float = 0.0
    preferred_symbols: list[str] = Field(default_factory=list)
    avoided_symbols: list[str] = Field(default_factory=list)
    preferred_market_states: list[str] = Field(default_factory=list)
    entry_conditions: list[str] = Field(default_factory=list)
    exit_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    historical_win_rate: float | None = None
    historical_rr: float | None = None
    sample_size: int = 0
    strategy_tier: str = "watchlist"
    tier_score: float = 0
    tier_rationale: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_posts: int = 0
    updated_at: str | None = None
    wins: int = 0
    losses: int = 0
    total_rr: float = 0
    avg_hold_hours: float = 0
    tp1_hit_rate: float = 0
    tp2_hit_rate: float = 0
    breakeven_exit_rate: float = 0
    max_drawdown_rr: float = 0


class StrategyLeaderboardEntry(StrategyCardStatsResponse):
    rank_score: float = 0
    tier: str = "watchlist"
    rationale: list[str] = Field(default_factory=list)


def _build_card_response(card, metrics) -> StrategyCardStatsResponse:
    tier_decision = compute_strategy_tier(
        sample_size=metrics.sample_size if metrics else card.sample_size,
        win_rate=metrics.win_rate if metrics else (card.historical_win_rate or 0),
        avg_rr=metrics.avg_rr if metrics else (card.historical_rr or 0),
        tp1_hit_rate=metrics.tp1_hit_rate if metrics else 0,
        tp2_hit_rate=metrics.tp2_hit_rate if metrics else 0,
        breakeven_exit_rate=metrics.breakeven_exit_rate if metrics else 0,
        max_drawdown_rr=metrics.max_drawdown_rr if metrics else 0,
    )
    stored_tier = getattr(card, "strategy_tier", "watchlist")
    stored_score = getattr(card, "tier_score", 0.0)
    stored_rationale = getattr(card, "tier_rationale", [])
    if stored_tier == "watchlist" and stored_score == 0 and not stored_rationale:
        effective_tier = tier_decision.tier
        effective_score = tier_decision.score
        effective_rationale = tier_decision.rationale
    else:
        effective_tier = stored_tier
        effective_score = stored_score
        effective_rationale = stored_rationale or tier_decision.rationale
    return StrategyCardStatsResponse(
        name=card.name,
        description=card.description,
        market=card.market,
        timeframe=card.timeframe,
        creator=card.creator,
        confidence_bias=card.confidence_bias,
        preferred_symbols=card.preferred_symbols,
        avoided_symbols=card.avoided_symbols,
        preferred_market_states=card.preferred_market_states,
        entry_conditions=card.entry_conditions,
        exit_conditions=card.exit_conditions,
        invalidation_conditions=card.invalidation_conditions,
        risk_notes=card.risk_notes,
        historical_win_rate=metrics.win_rate if metrics else card.historical_win_rate,
        historical_rr=metrics.avg_rr if metrics else card.historical_rr,
        sample_size=metrics.sample_size if metrics else card.sample_size,
        strategy_tier=effective_tier,
        tier_score=effective_score,
        tier_rationale=effective_rationale,
        tags=card.tags,
        source_posts=card.source_posts,
        updated_at=card.updated_at.isoformat(),
        wins=metrics.wins if metrics else 0,
        losses=metrics.losses if metrics else 0,
        total_rr=metrics.total_rr if metrics else 0,
        avg_hold_hours=metrics.avg_hold_hours if metrics else 0,
        tp1_hit_rate=metrics.tp1_hit_rate if metrics else 0,
        tp2_hit_rate=metrics.tp2_hit_rate if metrics else 0,
        breakeven_exit_rate=metrics.breakeven_exit_rate if metrics else 0,
        max_drawdown_rr=metrics.max_drawdown_rr if metrics else 0,
    )


def _leaderboard_score(card: StrategyCardStatsResponse) -> float:
    return round(card.tier_score, 3)


def _leaderboard_tier(card: StrategyCardStatsResponse, rank_score: float) -> str:
    return card.strategy_tier


def _leaderboard_rationale(card: StrategyCardStatsResponse) -> list[str]:
    return card.tier_rationale


@router.get("", response_model=list[StrategyCardStatsResponse])
def list_strategy_cards(session: Session = Depends(get_session)) -> list[StrategyCardStatsResponse]:
    store = StrategyStore()
    metrics_repo = StrategyMetricRepository(session)
    cards = []
    for card in store.list_cards():
        metrics = metrics_repo.get_by_strategy_name(card.name)
        cards.append(_build_card_response(card, metrics))
    return sorted(cards, key=lambda item: (item.historical_win_rate or 0, item.sample_size), reverse=True)


@router.get("/leaderboard", response_model=list[StrategyLeaderboardEntry])
def get_strategy_leaderboard(limit: int = 10, session: Session = Depends(get_session)) -> list[StrategyLeaderboardEntry]:
    store = StrategyStore()
    metrics_repo = StrategyMetricRepository(session)
    rows: list[StrategyLeaderboardEntry] = []
    for card in store.list_cards():
        metrics = metrics_repo.get_by_strategy_name(card.name)
        response = _build_card_response(card, metrics)
        rank_score = _leaderboard_score(response)
        rows.append(
            StrategyLeaderboardEntry(
                **response.model_dump(),
                rank_score=rank_score,
                tier=_leaderboard_tier(response, rank_score),
                rationale=_leaderboard_rationale(response),
            )
        )
    rows.sort(key=lambda item: (item.tier == "core", item.tier == "candidate", item.rank_score), reverse=True)
    return rows[:limit]


@router.get("/{name}", response_model=StrategyCardStatsResponse)
def get_strategy_card(name: str, session: Session = Depends(get_session)) -> StrategyCardStatsResponse:
    store = StrategyStore()
    card = store.load(name)
    if card is None:
        raise HTTPException(status_code=404, detail="strategy card not found")
    metrics = StrategyMetricRepository(session).get_by_strategy_name(card.name)
    return _build_card_response(card, metrics)
