from app.core.simulator import Simulator
from app.config import Settings
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
    trade = Simulator(settings=Settings(live_force_immediate_entry_for_testing=False)).open_trade(build_signal(), 50)

    assert trade.symbol == "BTCUSDT"
    assert trade.notional_usdt == 50
    assert trade.status == "pending_entry"
    assert trade.entry_confirmed is False
    assert trade.current_stop_loss == 95


def test_simulator_can_force_immediate_entry_for_local_live_testing():
    settings = Settings(use_simulation=True, live_force_immediate_entry_for_testing=True)
    trade = Simulator(settings=settings).open_trade(build_signal(), 50)

    assert trade.status == "open"
    assert trade.entry_mode == "market"
    assert trade.entry_confirmed is True
    assert trade.fees_paid_usdt == 50 * settings.simulation_fee_rate


def test_simulator_confirms_breakout_then_arms_tp1_profit_lock():
    simulator = Simulator(settings=Settings(live_force_immediate_entry_for_testing=False))
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

    locked = simulator.update_trade(
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
    assert locked.tp1_hit is True
    assert locked.status == "open"
    assert locked.remaining_notional_usdt == locked.notional_usdt
    assert locked.current_stop_loss == locked.tp1_price


def test_simulator_closes_when_price_retraces_back_to_tp1_lock():
    simulator = Simulator(settings=Settings(live_force_immediate_entry_for_testing=False))
    trade = simulator.open_trade(build_signal(), 100)
    trade.status = "open"
    trade.entry_confirmed = True

    armed = simulator.update_trade(
        trade,
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
    closed = simulator.update_trade(
        armed,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=105.0,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=5.5,
            btc_trend="up",
            follow_through_score=0.55,
            retest_quality_score=0.6,
        ),
    )

    assert closed.status == "closed"
    assert closed.exit_reason == "take profit lock retraced at tp1"
    assert closed.remaining_notional_usdt == 0


def test_simulator_arms_tp3_and_closes_on_retrace_to_tp3():
    simulator = Simulator(settings=Settings(live_force_immediate_entry_for_testing=False))
    trade = simulator.open_trade(build_signal(), 100)
    trade.status = "open"
    trade.entry_confirmed = True

    armed_tp1 = simulator.update_trade(
        trade,
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
    armed_tp2 = simulator.update_trade(
        armed_tp1,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=110.3,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=9,
            btc_trend="up",
            follow_through_score=0.8,
            retest_quality_score=0.7,
        ),
    )
    armed_tp3 = simulator.update_trade(
        armed_tp2,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=112.3,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=11,
            btc_trend="up",
            follow_through_score=0.85,
            retest_quality_score=0.72,
        ),
    )

    assert armed_tp3.trail_active is True
    assert armed_tp3.current_stop_loss == armed_tp3.take_profit

    closed = simulator.update_trade(
        armed_tp3,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=112.0,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=10.2,
            btc_trend="up",
            follow_through_score=0.75,
            retest_quality_score=0.68,
        ),
    )

    assert closed.status == "closed"
    assert closed.exit_reason == "take profit lock retraced at tp3"


def test_simulator_trails_above_target_with_atr_after_price_runs():
    simulator = Simulator(settings=Settings(live_force_immediate_entry_for_testing=False, target_trailing_atr_multiplier=1.5))
    trade = simulator.open_trade(build_signal(), 100)
    trade.status = "open"
    trade.entry_confirmed = True

    running = simulator.update_trade(
        trade,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=120,
            atr=2,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=13,
            btc_trend="up",
            follow_through_score=0.85,
            retest_quality_score=0.72,
        ),
    )

    assert running.trail_active is True
    assert running.current_stop_loss == 117

    still_open = simulator.update_trade(
        running,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=117.5,
            atr=2,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=11,
            btc_trend="up",
            follow_through_score=0.7,
            retest_quality_score=0.68,
        ),
    )
    assert still_open.status == "open"

    closed = simulator.update_trade(
        still_open,
        MarketSnapshot(
            symbol="BTCUSDT",
            price=116.9,
            atr=2,
            quote_volume_24h=100_000_000,
            price_change_pct_24h=10,
            btc_trend="up",
            follow_through_score=0.65,
            retest_quality_score=0.62,
        ),
    )

    assert closed.status == "closed"
    assert closed.exit_reason == "take profit lock retraced at tp3"


def test_simulator_exits_when_security_risk_flips_critical():
    simulator = Simulator(settings=Settings(live_force_immediate_entry_for_testing=False))
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
    simulator = Simulator(settings=Settings(live_force_immediate_entry_for_testing=False))
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
