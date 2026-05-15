from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class StructureType(StrEnum):
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    PULLBACK = "pullback"
    SENTIMENT = "sentiment"
    UNKNOWN = "unknown"


class MarketSnapshot(BaseModel):
    symbol: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    price: float
    volume_24h: float = 0
    price_change_pct_24h: float = 0
    quote_volume_24h: float = 0
    oi: float | None = None
    funding_rate: float | None = None
    long_short_ratio: float | None = None
    taker_buy_sell_ratio: float | None = None
    btc_trend: str = "unknown"
    market_regime: str = "unknown"
    reversal_stage: str = "unknown"
    relative_strength_score: float = 0.5
    sector_strength_score: float = 0.5
    retest_quality_score: float = 0.5
    follow_through_score: float = 0.5
    onchain_signal_score: float = 0.0
    onchain_wallet_count: int = 0
    onchain_buy_amount_usd: float = 0.0
    onchain_sold_ratio_percent: float | None = None
    onchain_wallet_types: list[str] = Field(default_factory=list)
    onchain_risk_level: str = "unknown"
    onchain_risk_tags: list[str] = Field(default_factory=list)
    onchain_honeypot: bool = False
    onchain_is_safe_buy: bool | None = None
    onchain_top10_holder_percent: float | None = None
    onchain_dev_holding_percent: float | None = None
    onchain_bundle_holding_percent: float | None = None
    onchain_suspicious_holding_percent: float | None = None
    onchain_liquidity_usd: float | None = None
    source: str = "binance"


class Candidate(BaseModel):
    snapshot: MarketSnapshot
    hard_score: float
    tags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    symbol: str
    structure: StructureType = StructureType.UNKNOWN
    direction: Direction = Direction.NEUTRAL
    confidence: float = 0
    rr: float = 0
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: list[str] = Field(default_factory=list)
    management_plan: list[str] = Field(default_factory=list)


class RiskDecision(BaseModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)
    position_notional_usdt: float = 0


class TradeSignal(BaseModel):
    symbol: str
    direction: Direction
    confidence: float
    rr: float
    score: float
    entry: float
    stop_loss: float
    take_profit: float
    structure: StructureType
    reasons: list[str] = Field(default_factory=list)
    management_plan: list[str] = Field(default_factory=list)
    primary_strategy_name: str | None = None
    matched_strategy_names: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StrategyMatchDiagnostic(BaseModel):
    name: str
    tier: str = "watchlist"
    tier_score: float = 0.0
    applied_bonus: float = 0.0
    weight_multiplier: float = 1.0
    symbol_match: bool = False
    notes: list[str] = Field(default_factory=list)


class CandidateDiagnostic(BaseModel):
    symbol: str
    snapshot: MarketSnapshot
    hard_score: float
    tags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    analysis: AnalysisResult
    risk: RiskDecision
    tradeable: bool
    signal: TradeSignal | None = None
    strategy_tier_mode: str = "all"
    strategy_matches: list[StrategyMatchDiagnostic] = Field(default_factory=list)
