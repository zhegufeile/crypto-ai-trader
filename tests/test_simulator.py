from app.core.simulator import Simulator
from app.data.schema import Direction, MarketSnapshot, StructureType, TradeSignal


def build_signal() -> TradeSignal:
    return TradeSignal(
        symbol="BTCUSDT",
        direction=Direction.LONG,
        confidence=0.8,
        rr=2.5,
        score=88,
        entry=100,
        stop_loss=95,
        take_profit=112,
        structure=StructureType.BREAKOUT,
        management_plan=[
            "do not widen the initial stop once the trade is live",
            "if expansion fails to continue soon after entry, exit instead of hoping for delayed follow-through",
        ],
    )


def test_simulator_opens_trade_with_confirmation_for_breakout():
    trade = Simulator().open_trade(build_signal(), 50)

    assert trade.symbol == "BTCUSDT"
    assert trade.notional_usdt == 50
    assert trade.status == "pending_entry"
    assert trade.entry_confirmed is False
    assert trade.current_stop_loss == 95


def test_simulator_confirms_breakout_then_scales_out():
    simulator = Simulator()
    trade = simulator.open_trade(build_signal(), 100)

    confirmed = simulator.update_trade(
        trade,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=100.4,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=5,
            btc_trend="up",
            follow_through_score=0.6,
            retest_quality_score=0.6,
        ),
    )
    assert confirmed.status == "open"
    assert confirmed.entry_confirmed is True

    scaled = simulator.update_trade(
        confirmed,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=105.2,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=6,
            btc_trend="up",
            follow_through_score=0.7,
            retest_quality_score=0.65,
        ),
    )
    assert scaled.tp1_hit is True
    assert scaled.status == "partial"
    assert scaled.remaining_notional_usdt < scaled.notional_usdt
    assert scaled.current_stop_loss >= scaled.entry


def test_simulator_exits_when_security_risk_flips_critical():
    simulator = Simulator()
    trade = simulator.open_trade(build_signal(), 100)
    trade.status = "open"
    trade.entry_confirmed = True

    closed = simulator.update_trade(
        trade,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=101,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=5,
            btc_trend="up",
            onchain_honeypot=True,
            onchain_is_safe_buy=False,
            onchain_risk_level="CRITICAL",
        ),
    )

    assert closed.status == "closed"
    assert closed.exit_reason == "security risk invalidated the trade"


def test_simulator_cancels_pending_trade_after_timeout():
    simulator = Simulator()
    trade = simulator.open_trade(build_signal(), 100)
    trade.opened_at = trade.opened_at.replace(year=trade.opened_at.year - 1)

    cancelled = simulator.update_trade(
        trade,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=100.1,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=5,
            btc_trend="up",
            follow_through_score=0.3,
            retest_quality_score=0.3,
        ),
    )

    assert cancelled.status == "cancelled"
    assert cancelled.exit_reason == "entry confirmation timed out"
