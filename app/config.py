from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    use_simulation: bool = True
    database_url: str = "sqlite:///./crypto_ai_trader.db"

    scan_interval_seconds: int = 300
    max_candidates: int = 10
    candidate_buffer_multiplier: int = 2
    snapshot_fetch_concurrency: int = 4
    confidence_threshold: float = 0.70
    min_rr: float = 2.0
    min_volume_usdt: float = 50_000_000
    min_relative_strength_score: float = 0.58
    min_follow_through_score: float = 0.45
    min_retest_quality_score: float = 0.52
    signal_strategy_tier_mode: str = "core+candidate"
    core_strategy_bonus_multiplier: float = 1.4
    candidate_strategy_bonus_multiplier: float = 1.0
    watchlist_strategy_bonus_multiplier: float = 0.45
    tier_score_bonus_scale: float = 0.06

    max_position_notional_usdt: float = 100
    max_open_positions: int = 3
    max_same_direction_positions: int = 2
    max_same_structure_positions: int = 2
    daily_max_loss_usdt: float = 50
    max_consecutive_losses: int = 2
    symbol_cooldown_minutes: int = 90
    pending_entry_timeout_minutes: int = 30
    trade_action_circuit_window_minutes: int = 15
    max_trade_actions_in_window: int = 6
    max_trade_state_changes_per_scan: int = 4
    blacklisted_symbols: list[str] = Field(default_factory=list)

    market_data_source: str = "binance"
    binance_base_url: str = "https://fapi.binance.com"
    binance_spot_base_url: str = "https://api.binance.com"
    binance_proxy_url: str | None = None
    binance_proxy_fallback_enabled: bool = True
    coinglass_api_key: str | None = None
    enable_onchain_signal_boost: bool = True
    onchain_signal_snapshot_file: str | None = None
    min_onchain_signal_score: float = 0.55
    onchain_risk_snapshot_file: str | None = None

    openai_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None
    frontend_origins: list[str] = Field(default_factory=list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
