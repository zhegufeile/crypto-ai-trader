from app.config import Settings
from app.core.live_trader import BinanceLiveTrader, BinanceLiveTradingError
from app.core.execution_engine import ExecutionEngine
from app.core.simulator import SimulatedTrade
from app.data.schema import Direction, MarketSnapshot, RiskDecision, StructureType, TradeSignal


class FakeLiveTrader:
    def __init__(self) -> None:
        self.open_called = False
        self.update_called = False

    def open_trade(self, signal: TradeSignal, notional_usdt: float) -> SimulatedTrade:
        self.open_called = True
        return SimulatedTrade(
            symbol=signal.symbol,
            direction=signal.direction.value,
            structure=signal.structure.value,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            notional_usdt=notional_usdt,
            remaining_notional_usdt=notional_usdt,
            initial_stop_loss=signal.stop_loss,
            current_stop_loss=signal.stop_loss,
            tp1_price=signal.entry * 1.01,
            tp2_price=signal.entry * 1.02,
        )

    def update_trade(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> SimulatedTrade:
        self.update_called = True
        trade.last_price = snapshot.price
        return trade


def build_signal() -> TradeSignal:
    return TradeSignal(
        symbol="BTCUSDT",
        direction=Direction.LONG,
        confidence=0.8,
        rr=2.2,
        score=1.5,
        entry=100000,
        stop_loss=98000,
        take_profit=104000,
        structure=StructureType.PULLBACK,
        reasons=["test"],
    )


def test_execution_engine_uses_live_trader_when_simulation_disabled():
    engine = ExecutionEngine(settings=Settings(use_simulation=False, live_trading_enabled=True))
    fake_live = FakeLiveTrader()
    engine.live_trader = fake_live

    trade = engine.execute_simulated(
        build_signal(),
        RiskDecision(allowed=True, position_notional_usdt=200, reasons=["ok"]),
    )

    assert trade is not None
    assert fake_live.open_called is True


def test_execution_engine_routes_management_to_live_trader():
    engine = ExecutionEngine(settings=Settings(use_simulation=False, live_trading_enabled=True))
    fake_live = FakeLiveTrader()
    engine.live_trader = fake_live
    trade = fake_live.open_trade(build_signal(), 200)
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=100500)

    managed = engine.manage_simulated(trade, snapshot)

    assert managed.last_price == 100500
    assert fake_live.update_called is True


def test_live_trader_stop_order_uses_close_position_without_quantity(monkeypatch):
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))
    captured = {}

    monkeypatch.setattr(
        trader,
        "_get_symbol_rules",
        lambda symbol: {"tick_size": 0.1, "step_size": 0.001, "min_qty": 0.001, "min_notional": 5},
    )

    def fake_signed_request(method, path, params, tolerate_errors=False):
        captured["params"] = params
        return {}

    monkeypatch.setattr(trader, "_signed_request", fake_signed_request)
    trade = SimulatedTrade(
        symbol="BTCUSDT",
        direction="long",
        structure="pullback",
        entry=100000,
        stop_loss=98000,
        take_profit=104000,
        notional_usdt=200,
        remaining_notional_usdt=200,
        initial_stop_loss=98000,
        current_stop_loss=98000,
        tp1_price=101000,
        tp2_price=102000,
    )

    trader._place_exchange_stop(trade, "0.002")

    assert captured["params"]["algoType"] == "CONDITIONAL"
    assert captured["params"]["closePosition"] == "true"
    assert captured["params"]["triggerPrice"] == "98000"
    assert "quantity" not in captured["params"]


def test_live_trader_ensure_exchange_protection_places_missing_stop_once(monkeypatch):
    trader = BinanceLiveTrader(
        settings=Settings(
            use_simulation=False,
            live_trading_enabled=True,
            live_protection_retry_attempts=1,
            live_protection_retry_delay_seconds=0,
        )
    )
    placed: list[str] = []

    call_count = {"value": 0}

    def list_open_orders(symbol):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return []
        return [
            {"orderType": "STOP_MARKET", "closePosition": "true"},
        ]

    monkeypatch.setattr(trader, "_list_open_algo_orders", list_open_orders)
    monkeypatch.setattr(trader, "_list_open_orders", lambda symbol: [])
    monkeypatch.setattr(trader, "_place_exchange_stop", lambda trade, qty: placed.append(f"stop:{trade.symbol}"))

    trade = SimulatedTrade(
        symbol="BTCUSDT",
        direction="long",
        structure="pullback",
        entry=100000,
        stop_loss=98000,
        take_profit=104000,
        notional_usdt=200,
        remaining_notional_usdt=200,
        initial_stop_loss=98000,
        current_stop_loss=98000,
        tp1_price=101000,
        tp2_price=102000,
    )

    trader._ensure_exchange_protection(trade)

    assert placed == ["stop:BTCUSDT"]


def test_live_trader_ensure_exchange_protection_retries_before_failing(monkeypatch):
    trader = BinanceLiveTrader(
        settings=Settings(
            use_simulation=False,
            live_trading_enabled=True,
            live_protection_retry_attempts=3,
            live_protection_retry_delay_seconds=0,
        )
    )
    attempts = {"stop": 0}

    monkeypatch.setattr(trader, "_list_open_algo_orders", lambda symbol: [])
    monkeypatch.setattr(trader, "_list_open_orders", lambda symbol: [])

    def fail_stop(trade, qty):
        attempts["stop"] += 1
        raise RuntimeError("stop failed")

    monkeypatch.setattr(trader, "_place_exchange_stop", fail_stop)

    trade = SimulatedTrade(
        symbol="BTCUSDT",
        direction="long",
        structure="pullback",
        entry=100000,
        stop_loss=98000,
        take_profit=104000,
        notional_usdt=200,
        remaining_notional_usdt=200,
        initial_stop_loss=98000,
        current_stop_loss=98000,
        tp1_price=101000,
        tp2_price=102000,
    )

    try:
        trader._ensure_exchange_protection(trade)
    except Exception as exc:
        assert "failed to install exchange protection after 3 attempts" in str(exc)
    else:
        raise AssertionError("expected protection installation to fail")

    assert attempts["stop"] == 3


def test_live_trader_ensure_exchange_protection_accepts_stop_seen_in_diagnostic_snapshot(monkeypatch):
    trader = BinanceLiveTrader(
        settings=Settings(
            use_simulation=False,
            live_trading_enabled=True,
            live_protection_retry_attempts=2,
            live_protection_retry_delay_seconds=0,
        )
    )
    attempts = {"list": 0, "place": 0}

    def fail_initial_lookup(symbol):
        attempts["list"] += 1
        raise RuntimeError("temporary connectivity issue")

    def place_stop(trade, qty):
        attempts["place"] += 1

    monkeypatch.setattr(trader, "_list_open_algo_orders", fail_initial_lookup)
    monkeypatch.setattr(trader, "_list_open_orders", lambda symbol: [])
    monkeypatch.setattr(trader, "_place_exchange_stop", place_stop)
    monkeypatch.setattr(
        trader,
        "_build_protection_diagnostic_snapshot",
        lambda trade, error, attempts: {
            "symbol": trade.symbol,
            "attempts": attempts,
            "open_orders": [],
            "open_algo_orders": [{"orderType": "STOP_MARKET", "closePosition": True}],
        },
    )

    trade = SimulatedTrade(
        symbol="BTCUSDT",
        direction="long",
        structure="pullback",
        entry=100000,
        stop_loss=98000,
        take_profit=104000,
        notional_usdt=200,
        remaining_notional_usdt=200,
        initial_stop_loss=98000,
        current_stop_loss=98000,
        tp1_price=101000,
        tp2_price=102000,
    )

    trader._ensure_exchange_protection(trade)

    assert attempts["list"] == 2
    assert attempts["place"] == 0


def test_live_trader_cancel_protection_orders_uses_algo_endpoint(monkeypatch):
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))
    captured: list[tuple[str, str, dict[str, object], bool]] = []

    monkeypatch.setattr(
        trader,
        "_list_open_algo_orders",
        lambda symbol: [
            {"orderType": "STOP_MARKET", "closePosition": "true", "algoId": 12345},
            {"orderType": "TAKE_PROFIT_MARKET", "closePosition": "true", "clientAlgoId": "tp-1"},
            {"orderType": "LIMIT", "closePosition": "false", "algoId": 999},
        ],
    )

    def fake_signed_request(method, path, params, tolerate_errors=False):
        captured.append((method, path, params, tolerate_errors))
        return {}

    monkeypatch.setattr(trader, "_signed_request", fake_signed_request)

    trader._cancel_protection_orders("BTCUSDT")

    assert captured == [
        ("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": "BTCUSDT"}, True),
        ("DELETE", "/fapi/v1/algoOrder", {"symbol": "BTCUSDT", "algoId": 12345}, True),
        ("DELETE", "/fapi/v1/algoOrder", {"symbol": "BTCUSDT", "clientAlgoId": "tp-1"}, True),
    ]


def test_live_trader_reduce_only_close_clears_algo_orders_first(monkeypatch):
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))
    captured: list[tuple[str, str, dict[str, object], bool]] = []

    monkeypatch.setattr(
        trader,
        "_get_position_risk",
        lambda symbol: {"positionAmt": "2.5"},
    )
    monkeypatch.setattr(
        trader,
        "_get_symbol_rules",
        lambda symbol: {"tick_size": 0.1, "step_size": 0.001, "min_qty": 0.001, "min_notional": 5},
    )

    def fake_signed_request(method, path, params, tolerate_errors=False):
        captured.append((method, path, params, tolerate_errors))
        return {}

    monkeypatch.setattr(trader, "_signed_request", fake_signed_request)
    monkeypatch.setattr(trader, "_list_open_algo_orders", lambda symbol: [])

    trader._reduce_only_close("BTCUSDT", "long", 1.0)

    assert captured[0] == ("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": "BTCUSDT"}, True)
    assert captured[1] == ("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": "BTCUSDT"}, True)
    assert captured[2][0:3] == (
        "POST",
        "/fapi/v1/order",
        {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "MARKET",
            "quantity": "2.5",
            "reduceOnly": "true",
            "newOrderRespType": "RESULT",
        },
    )


def test_live_trader_detects_reduce_only_stop_as_valid_protection(monkeypatch):
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))

    monkeypatch.setattr(trader, "_list_open_algo_orders", lambda symbol: [])
    monkeypatch.setattr(
        trader,
        "_list_open_orders",
        lambda symbol: [
            {"type": "STOP_MARKET", "reduceOnly": "true"},
        ],
    )

    assert trader._has_exchange_stop_protection("BTCUSDT") is True


def test_live_trader_detects_algo_order_type_field_as_valid_protection(monkeypatch):
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))

    monkeypatch.setattr(
        trader,
        "_list_open_algo_orders",
        lambda symbol: [
            {"orderType": "STOP_MARKET", "closePosition": "true"},
        ],
    )
    monkeypatch.setattr(trader, "_list_open_orders", lambda symbol: [])

    assert trader._has_exchange_stop_protection("BTCUSDT") is True


def test_live_trader_pending_trade_syncs_to_open_when_exchange_position_exists(monkeypatch):
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))
    ensured = {"called": False}

    monkeypatch.setattr(
        trader,
        "_get_position_risk",
        lambda symbol: {
            "positionAmt": "0.25",
            "entryPrice": "100000",
            "markPrice": "100100",
            "unRealizedProfit": "0.5",
        },
    )
    monkeypatch.setattr(trader, "_ensure_exchange_protection", lambda trade: ensured.__setitem__("called", True))

    trade = SimulatedTrade(
        symbol="BTCUSDT",
        direction="long",
        structure="breakout",
        entry=100000,
        stop_loss=98000,
        take_profit=104000,
        notional_usdt=200,
        remaining_notional_usdt=200,
        initial_stop_loss=98000,
        current_stop_loss=98000,
        tp1_price=101000,
        tp2_price=102000,
        status="pending_entry",
        entry_mode="confirm_breakout_hold",
        entry_confirmed=False,
        confirmation_required=True,
        fees_paid_usdt=0,
    )
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=100100)

    updated = trader.update_trade(trade, snapshot)

    assert updated.status == "open"
    assert updated.entry_confirmed is True
    assert updated.last_price == 100100
    assert updated.fees_paid_usdt > 0
    assert ensured["called"] is True


def test_live_trader_update_trade_finalizes_when_exchange_position_is_already_flat(monkeypatch):
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))

    monkeypatch.setattr(
        trader,
        "_get_position_risk",
        lambda symbol: {
            "positionAmt": "0",
            "entryPrice": "4.0033",
            "markPrice": "4.07",
            "unRealizedProfit": "0",
        },
    )

    trade = SimulatedTrade(
        symbol="LABUSDT",
        direction="short",
        structure="momentum",
        entry=4.0033,
        stop_loss=4.0611,
        take_profit=3.8451,
        notional_usdt=50,
        remaining_notional_usdt=50,
        initial_stop_loss=4.0611,
        current_stop_loss=4.0611,
        tp1_price=3.95,
        tp2_price=3.90,
        status="open",
        entry_mode="market",
        entry_confirmed=True,
        confirmation_required=False,
        quantity=12,
        remaining_quantity=12,
        fees_paid_usdt=0.02,
        last_price=4.07,
    )
    snapshot = MarketSnapshot(symbol="LABUSDT", price=4.08)

    updated = trader.update_trade(trade, snapshot)

    assert updated.status == "closed"
    assert updated.exit_reason == "exchange hard stop triggered"
    assert updated.realized_pnl_usdt < 0
    assert updated.unrealized_pnl_usdt == 0
    assert updated.pnl_usdt == updated.realized_pnl_usdt


def test_live_trader_blocks_new_entry_when_exchange_position_already_exists(monkeypatch):
    trader = BinanceLiveTrader(
        settings=Settings(
            use_simulation=False,
            live_trading_enabled=True,
            max_position_notional_usdt=250,
        )
    )
    monkeypatch.setattr(trader, "_assert_live_ready", lambda: None)
    monkeypatch.setattr(trader, "_assert_symbol_allowed", lambda symbol: None)
    monkeypatch.setattr(
        trader,
        "_get_position_risk",
        lambda symbol: {
            "positionAmt": "5",
            "entryPrice": "42.0",
            "markPrice": "42.2",
            "unRealizedProfit": "1.1",
        },
    )

    trade = SimulatedTrade(
        symbol="HYPEUSDT",
        direction="short",
        structure="momentum",
        entry=42.078,
        stop_loss=42.57,
        take_profit=40.3053,
        notional_usdt=50.0,
        remaining_notional_usdt=50.0,
        initial_stop_loss=42.57,
        current_stop_loss=42.57,
        tp1_price=41.6,
        tp2_price=40.9,
        status="open",
        entry_mode="market",
        entry_confirmed=True,
        confirmation_required=False,
    )

    try:
        trader._enter_live_position(trade)
    except BinanceLiveTradingError as exc:
        assert "already has an exchange position" in str(exc)
        assert exc.trade is not None
        assert exc.trade.status == "cancelled"
        assert exc.trade.exit_reason == "entry order was rejected by exchange"
    else:
        raise AssertionError("expected duplicate live position rejection")


def test_live_trader_rejected_entry_marks_trade_cancelled(monkeypatch):
    trader = BinanceLiveTrader(
        settings=Settings(
            use_simulation=False,
            live_trading_enabled=True,
            max_position_notional_usdt=250,
        )
    )
    monkeypatch.setattr(trader, "_assert_live_ready", lambda: None)
    monkeypatch.setattr(trader, "_assert_symbol_allowed", lambda symbol: None)
    monkeypatch.setattr(trader, "_configure_symbol", lambda symbol: None)
    monkeypatch.setattr(
        trader,
        "_get_symbol_rules",
        lambda symbol: {
            "tick_size": 0.1,
            "step_size": 0.001,
            "market_step_size": 1.0,
            "min_qty": 1.0,
            "min_notional": 5,
            "quantity_precision": 0,
        },
    )
    monkeypatch.setattr(trader, "_assert_account_capacity", lambda notional: None)
    monkeypatch.setattr(trader, "_get_mark_price", lambda symbol: 100.0)
    monkeypatch.setattr(
        trader,
        "_get_position_risk",
        lambda symbol: {
            "positionAmt": "0",
            "entryPrice": "0",
            "markPrice": "100",
            "unRealizedProfit": "0",
        },
    )

    def reject_request(method, path, params, tolerate_errors=False):
        raise BinanceLiveTradingError("binance http 400: precision rejected")

    monkeypatch.setattr(trader, "_signed_request", reject_request)

    trade = SimulatedTrade(
        symbol="BTCUSDT",
        direction="long",
        structure="breakout",
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        notional_usdt=200.0,
        remaining_notional_usdt=200.0,
        initial_stop_loss=95.0,
        current_stop_loss=95.0,
        tp1_price=101.0,
        tp2_price=102.0,
        status="open",
        entry_mode="market",
        entry_confirmed=True,
        confirmation_required=False,
    )

    try:
        trader._enter_live_position(trade)
    except BinanceLiveTradingError as exc:
        assert exc.trade is not None
        assert exc.trade.status == "cancelled"
        assert exc.trade.exit_reason == "entry order was rejected by exchange"
    else:
        raise AssertionError("expected exchange rejection")


def test_live_trader_rounds_quantity_to_market_precision():
    qty = BinanceLiveTrader._round_quantity(4380.6, 1.0, 0)
    assert qty == "4380"


def test_live_trader_round_down_with_integer_step_drops_fraction():
    qty = BinanceLiveTrader._round_down(49.9, 1.0)
    assert qty == "49"


def test_live_trader_retries_signed_request_after_timestamp_error(monkeypatch):
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))
    sync_calls: list[bool] = []
    request_calls = {"count": 0}

    monkeypatch.setattr(trader, "_sync_server_time", lambda force=False: sync_calls.append(force))

    def fake_request_with_fallback(method, path, params, headers):
        request_calls["count"] += 1
        if request_calls["count"] == 1:
            raise BinanceLiveTradingError("binance http 400 for request: {\"code\":-1021,\"msg\":\"Timestamp for this request is outside of the recvWindow.\"}")
        return {"ok": True, "timestamp": params["timestamp"]}

    monkeypatch.setattr(trader, "_request_with_fallback", fake_request_with_fallback)

    result = trader._signed_request("GET", "/fapi/v2/account", {})

    assert result["ok"] is True
    assert request_calls["count"] == 2
    assert sync_calls == [False, True]


def test_live_trader_preserves_protection_context_when_force_closed(monkeypatch):
    trader = BinanceLiveTrader(
        settings=Settings(
            use_simulation=False,
            live_trading_enabled=True,
            max_position_notional_usdt=250,
        )
    )
    monkeypatch.setattr(trader, "_assert_live_ready", lambda: None)
    monkeypatch.setattr(trader, "_assert_symbol_allowed", lambda symbol: None)
    monkeypatch.setattr(trader, "_configure_symbol", lambda symbol: None)
    monkeypatch.setattr(
        trader,
        "_get_symbol_rules",
        lambda symbol: {
            "tick_size": 0.1,
            "step_size": 0.001,
            "market_step_size": 0.001,
            "min_qty": 0.001,
            "min_notional": 5,
            "quantity_precision": 3,
        },
    )
    monkeypatch.setattr(trader, "_assert_account_capacity", lambda notional: None)
    monkeypatch.setattr(trader, "_get_mark_price", lambda symbol: 100.0)
    monkeypatch.setattr(trader, "_reduce_only_close", lambda symbol, direction, size_pct: None)
    position_calls = {"count": 0}

    def fake_position_risk(symbol):
        position_calls["count"] += 1
        if position_calls["count"] == 1:
            return {
                "positionAmt": "0",
                "entryPrice": "0",
                "markPrice": "100",
                "unRealizedProfit": "0",
            }
        return {
            "positionAmt": "2",
            "entryPrice": "100",
            "markPrice": "100",
            "unRealizedProfit": "0",
        }

    monkeypatch.setattr(trader, "_get_position_risk", fake_position_risk)

    def fake_signed_request(method, path, params, tolerate_errors=False):
        if path == "/fapi/v1/order":
            return {"status": "FILLED"}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(trader, "_signed_request", fake_signed_request)
    monkeypatch.setattr(
        trader,
        "_ensure_exchange_protection",
        lambda trade: (_ for _ in ()).throw(
            BinanceLiveTradingError(
                "failed to install exchange protection after 1 attempt: raw error",
                context={"error": "raw error", "attempts": 1},
            )
        ),
    )

    trade = SimulatedTrade(
        symbol="BTCUSDT",
        direction="long",
        structure="breakout",
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        notional_usdt=200.0,
        remaining_notional_usdt=200.0,
        initial_stop_loss=95.0,
        current_stop_loss=95.0,
        tp1_price=101.0,
        tp2_price=102.0,
        status="open",
        entry_mode="market",
        entry_confirmed=True,
        confirmation_required=False,
    )

    try:
        trader._enter_live_position(trade)
    except BinanceLiveTradingError as exc:
        assert exc.trade is not None
        assert exc.context == {"error": "raw error", "attempts": 1}
    else:
        raise AssertionError("expected protection failure")


def test_live_trader_ignores_position_mode_already_set_error():
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))

    ignored = trader._maybe_ignore_configuration_error(
        "/fapi/v1/positionSide/dual",
        BinanceLiveTradingError(
            'binance http 400 for request: {"code":-4059,"msg":"No need to change position side."}'
        ),
    )

    assert ignored == {"ignored": True}


def test_live_trader_ignores_margin_type_already_set_error():
    trader = BinanceLiveTrader(settings=Settings(use_simulation=False, live_trading_enabled=True))

    ignored = trader._maybe_ignore_configuration_error(
        "/fapi/v1/marginType",
        BinanceLiveTradingError(
            'binance http 400 for request: {"code":-4046,"msg":"No need to change margin type."}'
        ),
    )

    assert ignored == {"ignored": True}
