from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.core.simulator import SimulatedTrade
from app.core.risk_manager import RiskManager
from app.data.schema import AnalysisResult, Candidate, Direction, MarketSnapshot, StructureType


def test_risk_manager_allows_high_quality_signal():
    settings = Settings(confidence_threshold=0.7, min_rr=2.0, min_volume_usdt=1000)
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=100, quote_volume_24h=10_000)
    candidate = Candidate(snapshot=snapshot, hard_score=80)
    analysis = AnalysisResult(
        symbol="BTCUSDT",
        structure=StructureType.BREAKOUT,
        direction=Direction.LONG,
        confidence=0.8,
        rr=2.5,
    )

    decision = RiskManager(settings).evaluate(candidate, analysis)

    assert decision.allowed is True
    assert decision.position_notional_usdt == settings.max_position_notional_usdt


def test_risk_manager_blocks_low_rr():
    settings = Settings(confidence_threshold=0.7, min_rr=2.0, min_volume_usdt=1000)
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=100, quote_volume_24h=10_000)
    candidate = Candidate(snapshot=snapshot, hard_score=80)
    analysis = AnalysisResult(
        symbol="BTCUSDT",
        structure=StructureType.BREAKOUT,
        direction=Direction.LONG,
        confidence=0.8,
        rr=1.2,
    )

    decision = RiskManager(settings).evaluate(candidate, analysis)

    assert decision.allowed is False
    assert "risk/reward is below threshold" in decision.reasons


def test_risk_manager_blocks_range_chop_breakout():
    settings = Settings(confidence_threshold=0.7, min_rr=1.5, min_volume_usdt=1000)
    snapshot = MarketSnapshot(
        symbol="ETHUSDT",
        price=100,
        quote_volume_24h=10_000,
        market_regime="range_or_chop",
        follow_through_score=0.2,
    )
    candidate = Candidate(snapshot=snapshot, hard_score=80)
    analysis = AnalysisResult(
        symbol="ETHUSDT",
        structure=StructureType.BREAKOUT,
        direction=Direction.LONG,
        confidence=0.8,
        rr=2.1,
    )

    decision = RiskManager(settings).evaluate(candidate, analysis)

    assert decision.allowed is False
    assert "market regime is range or chop" in decision.reasons


def test_risk_manager_blocks_honeypot_token():
    settings = Settings(confidence_threshold=0.7, min_rr=1.5, min_volume_usdt=1000)
    snapshot = MarketSnapshot(
        symbol="SCAMUSDT",
        price=100,
        quote_volume_24h=10_000,
        onchain_honeypot=True,
        onchain_is_safe_buy=False,
        onchain_risk_level="CRITICAL",
        onchain_liquidity_usd=5000,
        relative_strength_score=0.8,
        follow_through_score=0.8,
    )
    candidate = Candidate(snapshot=snapshot, hard_score=80)
    analysis = AnalysisResult(
        symbol="SCAMUSDT",
        structure=StructureType.BREAKOUT,
        direction=Direction.LONG,
        confidence=0.9,
        rr=3.0,
    )

    decision = RiskManager(settings).evaluate(candidate, analysis)

    assert decision.allowed is False
    assert "onchain security flags this token as honeypot" in decision.reasons


def test_risk_manager_blocks_symbol_cooldown_and_loss_streak():
    settings = Settings(
        confidence_threshold=0.7,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_consecutive_losses=2,
        symbol_cooldown_minutes=120,
    )
    snapshot = MarketSnapshot(symbol="ETHUSDT", price=100, quote_volume_24h=10_000)
    candidate = Candidate(snapshot=snapshot, hard_score=80)
    analysis = AnalysisResult(
        symbol="ETHUSDT",
        structure=StructureType.BREAKOUT,
        direction=Direction.LONG,
        confidence=0.9,
        rr=2.4,
    )
    recent_closed = [
        SimulatedTrade(
            symbol="ETHUSDT",
            direction="long",
            structure="breakout",
            entry=100,
            stop_loss=95,
            take_profit=110,
            notional_usdt=100,
            remaining_notional_usdt=0,
            initial_stop_loss=95,
            current_stop_loss=95,
            tp1_price=105,
            tp2_price=110,
            status="closed",
            realized_pnl_usdt=-5,
            closed_at=datetime.now(UTC) - timedelta(minutes=10),
        ),
        SimulatedTrade(
            symbol="BTCUSDT",
            direction="long",
            structure="breakout",
            entry=100,
            stop_loss=95,
            take_profit=110,
            notional_usdt=100,
            remaining_notional_usdt=0,
            initial_stop_loss=95,
            current_stop_loss=95,
            tp1_price=105,
            tp2_price=110,
            status="closed",
            realized_pnl_usdt=-3,
            closed_at=datetime.now(UTC) - timedelta(minutes=30),
        ),
    ]

    decision = RiskManager(settings).evaluate(candidate, analysis, recent_closed_trades=recent_closed)

    assert decision.allowed is False
    assert "symbol is cooling down after a recent trade" in decision.reasons
    assert "consecutive loss cooldown is active" in decision.reasons


def test_risk_manager_blocks_same_direction_and_structure_exposure():
    settings = Settings(
        confidence_threshold=0.7,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_same_direction_positions=1,
        max_same_structure_positions=1,
    )
    snapshot = MarketSnapshot(symbol="SOLUSDT", price=100, quote_volume_24h=10_000)
    candidate = Candidate(snapshot=snapshot, hard_score=80)
    analysis = AnalysisResult(
        symbol="SOLUSDT",
        structure=StructureType.BREAKOUT,
        direction=Direction.LONG,
        confidence=0.85,
        rr=2.3,
    )
    active_trades = [
        SimulatedTrade(
            symbol="BTCUSDT",
            direction="long",
            structure="breakout",
            entry=100,
            stop_loss=95,
            take_profit=110,
            notional_usdt=100,
            remaining_notional_usdt=100,
            initial_stop_loss=95,
            current_stop_loss=95,
            tp1_price=105,
            tp2_price=110,
            status="open",
        )
    ]

    decision = RiskManager(settings).evaluate(candidate, analysis, active_trades=active_trades, open_positions=1)

    assert decision.allowed is False
    assert "same-direction exposure limit is reached" in decision.reasons
    assert "same-structure exposure limit is reached" in decision.reasons


def test_risk_manager_blocks_same_symbol_active_or_pending_position():
    settings = Settings(
        confidence_threshold=0.7,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=4,
        max_same_direction_positions=4,
        max_same_structure_positions=4,
    )
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=100, quote_volume_24h=10_000)
    candidate = Candidate(snapshot=snapshot, hard_score=80)
    analysis = AnalysisResult(
        symbol="BTCUSDT",
        structure=StructureType.BREAKOUT,
        direction=Direction.LONG,
        confidence=0.85,
        rr=2.3,
    )
    active_trades = [
        SimulatedTrade(
            symbol="BTCUSDT",
            direction="long",
            structure="breakout",
            entry=100,
            stop_loss=95,
            take_profit=110,
            notional_usdt=100,
            remaining_notional_usdt=100,
            initial_stop_loss=95,
            current_stop_loss=95,
            tp1_price=105,
            tp2_price=110,
            status="open",
        )
    ]

    decision = RiskManager(settings).evaluate(candidate, analysis, active_trades=active_trades, open_positions=1)

    assert decision.allowed is False
    assert "symbol already has an active or pending position" in decision.reasons


def test_risk_manager_allows_same_symbol_after_previous_trade_is_closed():
    settings = Settings(
        confidence_threshold=0.7,
        min_rr=1.5,
        min_volume_usdt=1000,
        max_open_positions=4,
        max_same_direction_positions=4,
        max_same_structure_positions=4,
    )
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=100, quote_volume_24h=10_000)
    candidate = Candidate(snapshot=snapshot, hard_score=80)
    analysis = AnalysisResult(
        symbol="BTCUSDT",
        structure=StructureType.BREAKOUT,
        direction=Direction.LONG,
        confidence=0.85,
        rr=2.3,
    )
    active_trades = [
        SimulatedTrade(
            symbol="BTCUSDT",
            direction="long",
            structure="breakout",
            entry=100,
            stop_loss=95,
            take_profit=110,
            notional_usdt=100,
            remaining_notional_usdt=0,
            initial_stop_loss=95,
            current_stop_loss=95,
            tp1_price=105,
            tp2_price=110,
            status="closed",
        )
    ]

    decision = RiskManager(settings).evaluate(candidate, analysis, active_trades=active_trades, open_positions=0)

    assert decision.allowed is True
    assert "symbol already has an active or pending position" not in decision.reasons
