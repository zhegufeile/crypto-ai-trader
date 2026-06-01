from app.ai.analyst import RuleBasedAnalyst
from app.config import Settings
from app.core.simulator import SimulatedTrade
from app.core.signal_engine import SignalEngine
from app.data.schema import Candidate, MarketSnapshot, StrategyMatchDiagnostic
from app.knowledge.distiller import StrategyCard


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
            return [
                StrategyMatchDiagnostic(
                    name="regime_aware_momentum_confluence_stable_gate",
                    tier="core",
                    applied_bonus=9.0,
                )
            ]
        return [
            StrategyMatchDiagnostic(
                name="regime_aware_momentum_confluence_aggressive",
                tier="candidate",
                applied_bonus=10.0,
            )
        ]

    monkeypatch.setattr(engine, "_apply_kol_cards", fake_strategy_matches)
    monkeypatch.setattr(
        engine.scorer,
        "score",
        lambda candidate, analysis: 80.0 if candidate.snapshot.symbol == "ETHUSDT" else 95.0,
    )

    signals = engine.generate_signals([confluence_candidate, aggressive_candidate])

    assert [signal.symbol for signal in signals] == ["ETHUSDT", "SOLUSDT"]
    assert signals[0].primary_strategy_name == "regime_aware_momentum_confluence_stable_gate"
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


def test_signal_engine_matches_new_stable_gate_card(monkeypatch):
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=3,
    )
    card = StrategyCard(
        name="regime_aware_momentum_confluence_stable_gate",
        description="stable gate",
        creator="tester",
        market="bullish",
        confidence_bias=0.16,
        preferred_market_states=["trend_or_acceleration", "uptrend_pullback"],
        entry_conditions=[
            "btc_backdrop_supportive",
            "sector_or_narrative_leadership_confirmed",
            "relative_strength_leader",
            "breakout",
            "volume_expansion",
            "oi_rising",
            "pullback_confirmation",
            "smart_money_signal_cluster",
            "first_retest_only",
            "confluence_gate_passed",
        ],
        invalidation_conditions=["range_or_chop", "failed_retest"],
        risk_notes=["respect the confluence gate"],
        strategy_tier="core",
        tier_score=0.88,
    )
    candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="PNKSTRUSDT",
            price=1.2,
            price_change_pct_24h=6.0,
            quote_volume_24h=120_000_000,
            oi=1000,
            funding_rate=0.0001,
            long_short_ratio=1.1,
            taker_buy_sell_ratio=1.15,
            btc_trend="up",
            market_regime="uptrend_pullback",
            reversal_stage="first_reversal",
            relative_strength_score=0.8,
            sector_strength_score=0.82,
            retest_quality_score=0.7,
            follow_through_score=0.75,
            breakout_acceptance_score=0.74,
            relative_volume_ratio=1.48,
            onchain_signal_score=0.9,
            onchain_wallet_count=4,
        ),
        hard_score=85,
    )
    engine = SignalEngine(settings=settings)
    monkeypatch.setattr(engine.strategy_store, "list_cards", lambda: [card])

    matches = engine._apply_kol_cards(candidate, strategy_tier_mode="core-only")

    assert len(matches) == 1
    assert matches[0].name == "regime_aware_momentum_confluence_stable_gate"
    assert matches[0].tier == "core"
    assert matches[0].applied_bonus > 0
    assert candidate.hard_score == 100


def test_signal_engine_rejects_new_stable_gate_when_confluence_is_weak(monkeypatch):
    settings = Settings(
        confidence_threshold=0.6,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=3,
    )
    card = StrategyCard(
        name="regime_aware_momentum_confluence_stable_gate",
        description="stable gate",
        creator="tester",
        market="bullish",
        confidence_bias=0.16,
        preferred_market_states=["trend_or_acceleration", "uptrend_pullback"],
        entry_conditions=[
            "btc_backdrop_supportive",
            "sector_or_narrative_leadership_confirmed",
            "relative_strength_leader",
            "breakout",
            "volume_expansion",
            "pullback_confirmation",
            "smart_money_signal_cluster",
            "first_retest_only",
            "confluence_gate_passed",
        ],
        invalidation_conditions=["range_or_chop", "failed_retest"],
        risk_notes=["respect the confluence gate"],
        strategy_tier="core",
        tier_score=0.88,
    )
    candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="PNKSTRUSDT",
            price=1.2,
            price_change_pct_24h=6.0,
            quote_volume_24h=120_000_000,
            oi=1000,
            funding_rate=0.0001,
            long_short_ratio=1.1,
            taker_buy_sell_ratio=1.15,
            btc_trend="down",
            market_regime="uptrend_pullback",
            reversal_stage="late_reversal",
            relative_strength_score=0.42,
            sector_strength_score=0.4,
            retest_quality_score=0.45,
            follow_through_score=0.75,
            breakout_acceptance_score=0.4,
            relative_volume_ratio=0.95,
            onchain_signal_score=0.2,
            onchain_wallet_count=1,
        ),
        hard_score=85,
    )
    engine = SignalEngine(settings=settings)
    monkeypatch.setattr(engine.strategy_store, "list_cards", lambda: [card])

    matches = engine._apply_kol_cards(candidate, strategy_tier_mode="core-only")

    assert matches == []
    assert candidate.hard_score == 85
    assert any("regime_aware_momentum_confluence_stable_gate" in reason for reason in candidate.reasons)
