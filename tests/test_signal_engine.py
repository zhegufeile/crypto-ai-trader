from app.ai.analyst import RuleBasedAnalyst
from app.config import Settings
from app.core.simulator import SimulatedTrade
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


def test_signal_engine_keeps_only_best_signal_per_symbol(monkeypatch):
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=3,
    )
    snapshot_fast = MarketSnapshot(
        symbol="SUIUSDT",
        price=4.1,
        price_change_pct_24h=5.5,
        quote_volume_24h=200_000_000,
        oi=1000,
        funding_rate=0.0001,
        long_short_ratio=1.1,
        taker_buy_sell_ratio=1.2,
        btc_trend="up",
    )
    snapshot_weaker = MarketSnapshot(
        symbol="SUIUSDT",
        price=4.08,
        price_change_pct_24h=4.2,
        quote_volume_24h=180_000_000,
        oi=900,
        funding_rate=0.0001,
        long_short_ratio=1.0,
        taker_buy_sell_ratio=1.1,
        btc_trend="up",
    )
    candidates = [
        Candidate(snapshot=snapshot_fast, hard_score=92, reasons=["strong candidate"]),
        Candidate(snapshot=snapshot_weaker, hard_score=80, reasons=["weaker candidate"]),
    ]
    engine = SignalEngine(settings=settings)
    scores = iter([82.0, 81.0])
    monkeypatch.setattr(engine.scorer, "score", lambda candidate, analysis: next(scores))

    signals = engine.generate_signals(candidates)

    assert len(signals) == 1
    assert signals[0].symbol == "SUIUSDT"
    assert signals[0].score == 80.0


def test_signal_engine_skips_symbol_with_active_trade():
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=4,
        max_same_direction_positions=4,
        max_same_structure_positions=4,
    )
    snapshot = MarketSnapshot(
        symbol="SUIUSDT",
        price=4.1,
        price_change_pct_24h=5.5,
        quote_volume_24h=200_000_000,
        oi=1000,
        funding_rate=0.0001,
        long_short_ratio=1.1,
        taker_buy_sell_ratio=1.2,
        btc_trend="up",
    )
    active_trade = SimulatedTrade(
        symbol="SUIUSDT",
        direction="long",
        structure="breakout",
        entry=4.1,
        stop_loss=3.9,
        take_profit=4.5,
        notional_usdt=50,
        remaining_notional_usdt=50,
        initial_stop_loss=3.9,
        current_stop_loss=3.9,
        tp1_price=4.3,
        tp2_price=4.5,
        status="pending_entry",
    )

    signals = SignalEngine(settings=settings).generate_signals(
        [Candidate(snapshot=snapshot, hard_score=92, reasons=["strong candidate"])],
        active_trades=[active_trade],
    )

    assert signals == []


def test_signal_engine_prioritizes_confluence_core_card(monkeypatch):
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=4,
    )
    confluence_candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="ETHUSDT",
            price=2500,
            price_change_pct_24h=3.5,
            quote_volume_24h=200_000_000,
            oi=1000,
            funding_rate=0.0001,
            long_short_ratio=1.1,
            taker_buy_sell_ratio=1.2,
            btc_trend="up",
            market_regime="uptrend_pullback",
            relative_strength_score=0.7,
            retest_quality_score=0.7,
            follow_through_score=0.6,
        ),
        hard_score=80,
    )
    aggressive_candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="SOLUSDT",
            price=150,
            price_change_pct_24h=7.0,
            quote_volume_24h=220_000_000,
            oi=1200,
            funding_rate=0.0001,
            long_short_ratio=1.15,
            taker_buy_sell_ratio=1.25,
            btc_trend="up",
            market_regime="trend_or_acceleration",
            relative_strength_score=0.75,
            retest_quality_score=0.62,
            follow_through_score=0.7,
        ),
        hard_score=90,
    )
    engine = SignalEngine(settings=settings)

    def fake_strategy_matches(candidate, strategy_tier_mode="all"):
        if candidate.snapshot.symbol == "ETHUSDT":
            return [StrategyMatchDiagnostic(name="core_confluence_pullback_breakout", tier="core", applied_bonus=9.0)]
        return [StrategyMatchDiagnostic(name="core_aggressive_theme_breakout", tier="core", applied_bonus=10.0)]

    monkeypatch.setattr(engine, "_apply_kol_cards", fake_strategy_matches)
    monkeypatch.setattr(
        engine.scorer,
        "score",
        lambda candidate, analysis: 80.0 if candidate.snapshot.symbol == "ETHUSDT" else 95.0,
    )

    signals = engine.generate_signals([confluence_candidate, aggressive_candidate])

    assert [signal.symbol for signal in signals] == ["ETHUSDT", "SOLUSDT"]
    assert signals[0].primary_strategy_name == "core_confluence_pullback_breakout"
    assert signals[0].score == 100.0
    assert signals[1].score == 93.0


def test_rule_based_analyst_prefers_htf_pullback_reclaim_direction_over_24h_color():
    snapshot = MarketSnapshot(
        symbol="ETHUSDT",
        price=2500,
        price_change_pct_24h=-1.9,
        quote_volume_24h=220_000_000,
        oi=1200,
        funding_rate=0.0001,
        long_short_ratio=1.08,
        taker_buy_sell_ratio=1.12,
        btc_trend="up",
        market_regime="uptrend_pullback",
        reversal_stage="trend",
        relative_strength_score=0.82,
        retest_quality_score=0.8,
        follow_through_score=0.72,
    )
    object.__setattr__(snapshot, "htf_trend_bias", 0.85)
    candidate = Candidate(snapshot=snapshot, hard_score=88, reasons=["bullish reclaim setup"])

    analysis = RuleBasedAnalyst().analyze(candidate)

    assert analysis.direction.value == "long"
    assert analysis.structure.value == "pullback"


def test_signal_engine_registers_new_confirmation_strategies():
    engine = SignalEngine(settings=Settings())

    strategy_names = {strategy.name for strategy in engine.strategies}

    assert "breakout_retest_confirmation" in strategy_names
    assert "htf_trend_pullback_reclaim" in strategy_names


def test_signal_engine_blocks_unconfirmed_overextended_breakout():
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=3,
    )
    snapshot = MarketSnapshot(
        symbol="SOLUSDT",
        price=150,
        price_change_pct_24h=8.4,
        quote_volume_24h=240_000_000,
        oi=1500,
        funding_rate=0.0001,
        long_short_ratio=1.15,
        taker_buy_sell_ratio=1.2,
        btc_trend="up",
        market_regime="trend_or_acceleration",
        reversal_stage="trend",
        relative_strength_score=0.8,
        retest_quality_score=0.62,
        follow_through_score=0.7,
    )
    object.__setattr__(snapshot, "htf_trend_bias", 0.8)
    object.__setattr__(snapshot, "breakout_acceptance_score", 0.2)
    object.__setattr__(snapshot, "relative_volume_ratio", 0.95)
    object.__setattr__(snapshot, "distance_from_vwap_atr", 1.65)
    object.__setattr__(snapshot, "distance_from_breakout_level_atr", 1.25)
    candidate = Candidate(snapshot=snapshot, hard_score=95, reasons=["extended breakout"])

    signals = SignalEngine(settings=settings).generate_signals([candidate])

    assert signals == []
