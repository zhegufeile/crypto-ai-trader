from app.config import Settings
from app.core.signal_engine import SignalEngine
from app.data.schema import Candidate, MarketSnapshot, StrategyMatchDiagnostic


def test_signal_engine_generates_signal_for_strong_candidate():
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=3,
    )
    snapshot = MarketSnapshot(
        symbol="ETHUSDT",
        price=2500,
        price_change_pct_24h=5.5,
        quote_volume_24h=200_000_000,
        oi=1000,
        funding_rate=0.0001,
        long_short_ratio=1.1,
        taker_buy_sell_ratio=1.2,
        btc_trend="up",
    )
    candidate = Candidate(snapshot=snapshot, hard_score=85, reasons=["test candidate"])

    signals = SignalEngine(settings=settings).generate_signals([candidate])

    assert len(signals) == 1
    assert signals[0].symbol == "ETHUSDT"
    assert signals[0].entry == 2500
    assert signals[0].management_plan


def test_signal_engine_skips_choppy_late_reversal_candidate():
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=3,
    )
    snapshot = MarketSnapshot(
        symbol="DOGEUSDT",
        price=0.2,
        price_change_pct_24h=0.8,
        quote_volume_24h=120_000_000,
        oi=1000,
        funding_rate=0.0001,
        long_short_ratio=1.0,
        taker_buy_sell_ratio=1.0,
        btc_trend="flat",
        market_regime="range_or_chop",
        reversal_stage="late_reversal",
        relative_strength_score=0.3,
        retest_quality_score=0.4,
        follow_through_score=0.2,
    )
    candidate = Candidate(snapshot=snapshot, hard_score=90, reasons=["test candidate"])

    signals = SignalEngine(settings=settings).generate_signals([candidate])

    assert signals == []


def test_signal_engine_carries_primary_strategy_name_into_signal(monkeypatch):
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=3,
    )
    snapshot = MarketSnapshot(
        symbol="ETHUSDT",
        price=2500,
        price_change_pct_24h=5.5,
        quote_volume_24h=200_000_000,
        oi=1000,
        funding_rate=0.0001,
        long_short_ratio=1.1,
        taker_buy_sell_ratio=1.2,
        btc_trend="up",
    )
    candidate = Candidate(snapshot=snapshot, hard_score=85, reasons=["test candidate"])
    engine = SignalEngine(settings=settings)
    monkeypatch.setattr(
        engine,
        "_apply_kol_cards",
        lambda candidate, strategy_tier_mode="all": [
            StrategyMatchDiagnostic(name="derrrrrrq_generic", tier="core", applied_bonus=12.0),
            StrategyMatchDiagnostic(name="onchainos_smart_money_gate", tier="watchlist", applied_bonus=3.0),
        ],
    )

    signals = engine.generate_signals([candidate])

    assert len(signals) == 1
    assert signals[0].primary_strategy_name == "derrrrrrq_generic"
    assert signals[0].matched_strategy_names == ["derrrrrrq_generic", "onchainos_smart_money_gate"]
