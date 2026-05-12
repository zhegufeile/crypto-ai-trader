from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class SignalRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    direction: str
    confidence: float
    rr: float
    score: float
    entry: float
    stop_loss: float
    take_profit: float
    structure: str
    reasons: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class SimTradeRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    symbol: str = Field(index=True)
    direction: str
    structure: str = "unknown"
    entry: float
    stop_loss: float
    take_profit: float
    notional_usdt: float
    remaining_notional_usdt: float = 0
    initial_stop_loss: float = 0
    current_stop_loss: float = 0
    tp1_price: float = 0
    tp2_price: float = 0
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp1_size_pct: float = 0.4
    tp2_size_pct: float = 0.35
    remaining_size_pct: float = 1.0
    status: str
    entry_mode: str = "market"
    entry_confirmed: bool = True
    confirmation_required: bool = False
    break_even_armed: bool = False
    trail_active: bool = False
    opened_at: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    closed_at: datetime | None = None
    last_price: float | None = None
    max_price_seen: float | None = None
    min_price_seen: float | None = None
    pnl_usdt: float = 0
    realized_pnl_usdt: float = 0
    unrealized_pnl_usdt: float = 0
    fees_paid_usdt: float = 0
    exit_reason: str | None = None
    management_plan: str = ""


class TradeJournalRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trade_id: str | None = Field(default=None, index=True)
    symbol: str = Field(index=True)
    event_type: str = Field(index=True)
    status: str = Field(default="info", index=True)
    message: str
    details: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class TradeFeeRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trade_id: str | None = Field(default=None, index=True)
    symbol: str = Field(index=True)
    event_type: str = Field(index=True)
    amount_usdt: float = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class KOLPostRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    strategy_name: str = Field(index=True)
    author: str = Field(index=True)
    source: str = Field(index=True)
    text: str
    created_at: datetime | None = Field(default=None, index=True)
    url: str | None = None
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    views: int = 0
    symbols: str = ""
    tags: str = ""
    raw_payload: str = ""
    imported_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class StrategyMetricRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    strategy_name: str = Field(index=True, unique=True)
    sample_size: int = 0
    win_rate: float = 0
    avg_rr: float = 0
    total_rr: float = 0
    wins: int = 0
    losses: int = 0
    avg_hold_hours: float = 0
    tp1_hit_rate: float = 0
    tp2_hit_rate: float = 0
    breakeven_exit_rate: float = 0
    max_drawdown_rr: float = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
