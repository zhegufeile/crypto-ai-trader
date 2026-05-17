import hashlib
import hmac
import time
from decimal import Decimal, ROUND_DOWN
import json
import re
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings
from app.core.simulator import SimulatedTrade, Simulator
from app.data.schema import MarketSnapshot, TradeSignal


class BinanceLiveTradingError(RuntimeError):
    def __init__(
        self,
        message: str,
        trade: SimulatedTrade | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.trade = trade
        self.context = context or {}


class BinanceLiveTrader:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.simulator = Simulator(settings=self.settings)
        self.base_url = (
            "https://testnet.binancefuture.com"
            if self.settings.binance_testnet
            else self.settings.binance_base_url.rstrip("/")
        )
        self.timeout = 15.0
        self._exchange_rules: dict[str, dict[str, float]] = {}
        self._server_time_offset_ms = 0
        self._server_time_synced_at = 0.0
        self._position_mode_configured = False
        self._margin_configured_symbols: set[str] = set()
        self._leverage_configured_symbols: set[str] = set()

    def open_trade(self, signal: TradeSignal, notional_usdt: float) -> SimulatedTrade:
        trade = self.simulator.open_trade(signal, notional_usdt)
        if trade.status == "pending_entry":
            return trade
        return self._enter_live_position(trade)

    def update_trade(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> SimulatedTrade:
        if not trade.is_active:
            return trade

        trade.updated_at = snapshot.timestamp
        trade.last_price = snapshot.price
        trade.max_price_seen = snapshot.price if trade.max_price_seen is None else max(trade.max_price_seen, snapshot.price)
        trade.min_price_seen = snapshot.price if trade.min_price_seen is None else min(trade.min_price_seen, snapshot.price)

        if trade.status in {"pending_entry", "entry_in_progress"}:
            return self._update_pending_trade(trade, snapshot)

        position = self._get_position_risk(trade.symbol)
        if abs(float(position.get("positionAmt", 0) or 0)) <= 0:
            exit_price = trade.current_stop_loss
            exit_reason = "exchange position already flat"
            if trade.last_price is not None and self.simulator._stop_triggered(trade, trade.last_price):
                exit_price = trade.current_stop_loss
                exit_reason = "exchange hard stop triggered"
            elif snapshot.price and self.simulator._stop_triggered(trade, snapshot.price):
                exit_price = trade.current_stop_loss
                exit_reason = "exchange hard stop triggered"
            elif trade.last_price:
                exit_price = trade.last_price
            elif snapshot.price:
                exit_price = snapshot.price
            self._finalize_closed_trade(trade, exit_price, trade.exit_reason or exit_reason)
            trade.closed_at = snapshot.timestamp
            return trade

        mark_price = float(position.get("markPrice", snapshot.price) or snapshot.price)
        entry_price = float(position.get("entryPrice", trade.entry) or trade.entry)
        trade.entry = entry_price
        trade.last_price = mark_price
        trade.unrealized_pnl_usdt = float(position.get("unRealizedProfit", 0) or 0)
        trade.pnl_usdt = trade.realized_pnl_usdt + trade.unrealized_pnl_usdt
        try:
            self._ensure_exchange_protection(trade)
        except BinanceLiveTradingError as exc:
            self._reduce_only_close(trade.symbol, trade.direction, 1.0)
            self._finalize_closed_trade(trade, mark_price, "exchange protection could not be installed")
            raise BinanceLiveTradingError(str(exc), trade=trade, context=exc.context) from exc

        if self.simulator._has_security_exit(snapshot):
            self._reduce_only_close(trade.symbol, trade.direction, 1.0)
            self._finalize_closed_trade(trade, mark_price, "security risk invalidated the trade")
            return trade

        if self.simulator._follow_through_failed(trade, snapshot):
            self._reduce_only_close(trade.symbol, trade.direction, 1.0)
            self._finalize_closed_trade(trade, mark_price, "follow-through failed after entry")
            return trade

        self._check_take_profit_steps(trade, mark_price)

        if self.simulator._stop_triggered(trade, mark_price):
            self._reduce_only_close(trade.symbol, trade.direction, 1.0)
            self._finalize_closed_trade(trade, trade.current_stop_loss, self.simulator._stop_exit_reason(trade))
            return trade

        return trade

    def _update_pending_trade(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> SimulatedTrade:
        position = self._get_position_risk(trade.symbol)
        if abs(float(position.get("positionAmt", 0) or 0)) > 0:
            trade = self._sync_live_trade(trade, snapshot, position)
            try:
                self._ensure_exchange_protection(trade)
            except BinanceLiveTradingError as exc:
                self._reduce_only_close(trade.symbol, trade.direction, 1.0)
                self._finalize_closed_trade(trade, trade.last_price or snapshot.price, "exchange protection could not be installed")
                raise BinanceLiveTradingError(str(exc), trade=trade, context=exc.context) from exc
            return trade
        age_minutes = max((time.time() - trade.opened_at.timestamp()) / 60, 0)
        if age_minutes >= self.settings.pending_entry_timeout_minutes:
            trade.status = "cancelled"
            trade.closed_at = snapshot.timestamp
            trade.exit_reason = "entry confirmation timed out"
            return trade
        if self.simulator._stop_triggered(trade, snapshot.price):
            trade.status = "cancelled"
            trade.closed_at = snapshot.timestamp
            trade.exit_reason = "setup failed before entry confirmation"
            return trade
        if self.simulator._entry_confirmation_passed(trade, snapshot):
            return self._enter_live_position(trade)
        if trade.status == "entry_in_progress":
            trade.status = "pending_entry"
        return trade

    def _enter_live_position(self, trade: SimulatedTrade) -> SimulatedTrade:
        self._assert_live_ready()
        self._assert_symbol_allowed(trade.symbol)
        entry_live = False
        try:
            self._assert_no_existing_exchange_position(trade.symbol)
            self._configure_symbol(trade.symbol)
            rules = self._get_symbol_rules(trade.symbol)
            self._assert_account_capacity(trade.notional_usdt)

            current_price = self._get_mark_price(trade.symbol)
            qty = self._calculate_quantity(trade.symbol, trade.notional_usdt, current_price, rules)
            trade.quantity = float(qty)
            trade.remaining_quantity = float(qty)
            side = "BUY" if trade.direction == "long" else "SELL"
            self._signed_request(
                "POST",
                "/fapi/v1/order",
                {
                    "symbol": trade.symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": qty,
                    "newOrderRespType": "RESULT",
                },
            )
            entry_live = True
            time.sleep(self.settings.live_order_check_seconds)
            position = self._get_position_risk(trade.symbol)
            if abs(float(position.get("positionAmt", 0) or 0)) <= 0:
                raise BinanceLiveTradingError(f"{trade.symbol} entry order filled without an active position snapshot")
            trade = self._sync_live_trade(trade, None, position)
            self._ensure_exchange_protection(trade)
            return trade
        except Exception as exc:
            if entry_live:
                try:
                    self._reduce_only_close(trade.symbol, trade.direction, 1.0)
                except Exception:
                    pass
                self._finalize_closed_trade(
                    trade,
                    trade.last_price or current_price,
                    "entry was force-closed because exchange protection could not be verified",
                )
            else:
                trade.status = "cancelled"
                trade.closed_at = trade.updated_at
                trade.exit_reason = "entry order was rejected by exchange"
            if isinstance(exc, BinanceLiveTradingError):
                raise BinanceLiveTradingError(str(exc), trade=trade, context=exc.context) from exc
            raise BinanceLiveTradingError(str(exc), trade=trade) from exc

    def _check_take_profit_steps(self, trade: SimulatedTrade, price: float) -> None:
        if not trade.tp1_hit and self.simulator._price_reached(trade.direction, price, trade.tp1_price):
            trade.tp1_hit = True
            trade.break_even_armed = True
            trade.current_stop_loss = self.simulator._better_stop(trade.direction, trade.current_stop_loss, trade.tp1_price)
            trade.status = "open"

        if trade.tp1_hit and not trade.tp2_hit and self.simulator._price_reached(trade.direction, price, trade.tp2_price):
            trade.tp2_hit = True
            trade.current_stop_loss = self.simulator._better_stop(trade.direction, trade.current_stop_loss, trade.tp2_price)
            trade.status = "open"

        if trade.tp2_hit and not trade.trail_active and self.simulator._price_reached(trade.direction, price, trade.take_profit):
            trade.trail_active = True
            trade.current_stop_loss = self.simulator._better_stop(trade.direction, trade.current_stop_loss, trade.take_profit)
            trade.status = "open"

    def _finalize_closed_trade(self, trade: SimulatedTrade, exit_price: float, reason: str) -> None:
        if trade.remaining_notional_usdt > 0:
            self.simulator._charge_fee(trade, trade.remaining_notional_usdt)
            trade.realized_pnl_usdt += self.simulator._pnl_for_fraction(
                trade.direction,
                trade.entry,
                exit_price,
                trade.remaining_notional_usdt,
            )
        trade.remaining_notional_usdt = 0
        trade.remaining_quantity = 0
        trade.remaining_size_pct = 0
        trade.unrealized_pnl_usdt = 0
        trade.pnl_usdt = trade.realized_pnl_usdt
        trade.status = "closed"
        trade.closed_at = trade.updated_at
        trade.exit_reason = reason

    def _place_exchange_stop(self, trade: SimulatedTrade, qty: str) -> None:
        side = "SELL" if trade.direction == "long" else "BUY"
        rules = self._get_symbol_rules(trade.symbol)
        stop_price = self._round_down(trade.stop_loss, rules["tick_size"])
        self._signed_request(
            "POST",
            "/fapi/v1/algoOrder",
            {
                "algoType": "CONDITIONAL",
                "symbol": trade.symbol,
                "side": side,
                "type": "STOP_MARKET",
                "triggerPrice": stop_price,
                "closePosition": "true",
                "workingType": "MARK_PRICE",
                "priceProtect": "FALSE",
            },
        )

    def _place_exchange_reduce_only_stop(self, trade: SimulatedTrade) -> None:
        side = "SELL" if trade.direction == "long" else "BUY"
        rules = self._get_symbol_rules(trade.symbol)
        stop_price = self._round_down(trade.stop_loss, rules["tick_size"])
        quantity = trade.remaining_quantity or trade.quantity
        qty_str = self._round_down(quantity, rules["step_size"])
        if float(qty_str) <= 0:
            raise BinanceLiveTradingError(f"{trade.symbol} reduce-only stop quantity resolved to zero")
        self._signed_request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": trade.symbol,
                "side": side,
                "type": "STOP_MARKET",
                "stopPrice": stop_price,
                "quantity": qty_str,
                "reduceOnly": "true",
                "workingType": "MARK_PRICE",
                "priceProtect": "FALSE",
            },
        )

    def _place_exchange_take_profit(self, trade: SimulatedTrade) -> None:
        side = "SELL" if trade.direction == "long" else "BUY"
        rules = self._get_symbol_rules(trade.symbol)
        take_profit_price = self._round_down(trade.take_profit, rules["tick_size"])
        self._signed_request(
            "POST",
            "/fapi/v1/algoOrder",
            {
                "algoType": "CONDITIONAL",
                "symbol": trade.symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": take_profit_price,
                "closePosition": "true",
                "workingType": "MARK_PRICE",
                "priceProtect": "FALSE",
            },
        )

    def _ensure_exchange_protection(self, trade: SimulatedTrade) -> None:
        attempts = max(1, self.settings.live_protection_retry_attempts)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if self._has_exchange_stop_protection(trade.symbol):
                    return
                self._place_exchange_stop(trade, "")
                time.sleep(self.settings.live_protection_retry_delay_seconds)
                if self._has_exchange_stop_protection(trade.symbol):
                    return
            except Exception as exc:
                last_error = exc

        context = self._build_protection_diagnostic_snapshot(
            trade,
            last_error,
            attempts=attempts,
        )
        if self._snapshot_has_exchange_stop_protection(context):
            return

        message = f"failed to install exchange protection after {attempts} attempt"
        if attempts != 1:
            message += "s"
        if last_error is not None:
            message = f"{message}: {last_error}"
        raise BinanceLiveTradingError(
            message,
            trade=trade,
            context=context,
        )

    def _has_exchange_stop_protection(self, symbol: str) -> bool:
        algo_orders = self._list_open_algo_orders(symbol)
        if any(
            self._algo_order_type(order) == "STOP_MARKET"
            and str(order.get("closePosition", "")).lower() == "true"
            for order in algo_orders
        ):
            return True
        regular_orders = self._list_open_orders(symbol)
        return any(
            order.get("type") == "STOP_MARKET"
            and str(order.get("reduceOnly", "")).lower() == "true"
            for order in regular_orders
        )

    def _snapshot_has_exchange_stop_protection(self, snapshot: dict[str, Any]) -> bool:
        algo_orders = snapshot.get("open_algo_orders", [])
        if any(
            self._algo_order_type(order) == "STOP_MARKET"
            and str(order.get("closePosition", "")).lower() == "true"
            for order in algo_orders
        ):
            return True
        regular_orders = snapshot.get("open_orders", [])
        return any(
            order.get("type") == "STOP_MARKET"
            and str(order.get("reduceOnly", "")).lower() == "true"
            for order in regular_orders
        )

    def _list_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        orders = self._signed_request("GET", "/fapi/v1/openOrders", {"symbol": symbol})
        if isinstance(orders, list):
            return orders
        return []

    def _list_open_algo_orders(self, symbol: str) -> list[dict[str, Any]]:
        orders = self._signed_request("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol})
        if isinstance(orders, list):
            return orders
        return []

    def _cancel_protection_orders(self, symbol: str) -> None:
        self._signed_request(
            "DELETE",
            "/fapi/v1/algoOpenOrders",
            {"symbol": symbol},
            tolerate_errors=True,
        )
        orders = self._list_open_algo_orders(symbol)
        for order in orders:
            if self._algo_order_type(order) not in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}:
                continue
            algo_id = order.get("algoId")
            client_algo_id = order.get("clientAlgoId")
            cancel_params: dict[str, Any] = {"symbol": symbol}
            if algo_id:
                cancel_params["algoId"] = algo_id
            elif client_algo_id:
                cancel_params["clientAlgoId"] = client_algo_id
            else:
                continue
            self._signed_request(
                "DELETE",
                "/fapi/v1/algoOrder",
                cancel_params,
                tolerate_errors=True,
            )

    def _clear_symbol_protection_conflicts(self, symbol: str) -> None:
        self._cancel_protection_orders(symbol)
        self._signed_request(
            "DELETE",
            "/fapi/v1/allOpenOrders",
            {"symbol": symbol},
            tolerate_errors=True,
        )

    def _reduce_only_close(self, symbol: str, direction: str, size_pct: float) -> None:
        position = self._get_position_risk(symbol)
        amt = abs(float(position.get("positionAmt", 0) or 0))
        if amt <= 0:
            return
        self._cancel_protection_orders(symbol)
        rules = self._get_symbol_rules(symbol)
        qty = amt * min(max(size_pct, 0.0), 1.0)
        qty_str = self._round_down(qty, rules["step_size"])
        if float(qty_str) <= 0:
            return
        side = "SELL" if direction == "long" else "BUY"
        self._signed_request(
            "DELETE",
            "/fapi/v1/algoOpenOrders",
            {"symbol": symbol},
            tolerate_errors=True,
        )
        self._signed_request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": qty_str,
                "reduceOnly": "true",
                "newOrderRespType": "RESULT",
            },
        )

    def _sync_live_trade(
        self,
        trade: SimulatedTrade,
        snapshot: MarketSnapshot | None,
        position: dict[str, Any],
    ) -> SimulatedTrade:
        mark_price = float(position.get("markPrice", snapshot.price if snapshot else trade.entry) or (snapshot.price if snapshot else trade.entry))
        entry_price = float(position.get("entryPrice", trade.entry) or trade.entry)
        trade.entry = entry_price
        trade.quantity = abs(float(position.get("positionAmt", trade.quantity) or trade.quantity))
        trade.last_price = mark_price
        trade.max_price_seen = mark_price if trade.max_price_seen is None else max(trade.max_price_seen, mark_price)
        trade.min_price_seen = mark_price if trade.min_price_seen is None else min(trade.min_price_seen, mark_price)
        trade.unrealized_pnl_usdt = float(position.get("unRealizedProfit", 0) or 0)
        trade.pnl_usdt = trade.realized_pnl_usdt + trade.unrealized_pnl_usdt
        trade.status = "open" if not trade.tp1_hit else "partial"
        trade.entry_confirmed = True
        trade.remaining_quantity = round(trade.quantity * trade.remaining_size_pct, 8)
        trade.updated_at = snapshot.timestamp if snapshot else trade.updated_at
        if trade.fees_paid_usdt <= 0:
            self.simulator._charge_fee(trade, trade.notional_usdt)
        return trade

    def _assert_live_ready(self) -> None:
        if self.settings.use_simulation:
            raise BinanceLiveTradingError("live trader cannot run while use_simulation is true")
        if not self.settings.live_trading_enabled:
            raise BinanceLiveTradingError("live trading is disabled by configuration")
        if not self.settings.binance_api_key or not self.settings.binance_api_secret:
            raise BinanceLiveTradingError("binance api credentials are missing")

    def _assert_symbol_allowed(self, symbol: str) -> None:
        whitelist = {item.upper() for item in self.settings.live_whitelisted_symbols}
        if whitelist and symbol.upper() not in whitelist:
            raise BinanceLiveTradingError(f"{symbol} is not in the live trading whitelist")

    def _assert_no_existing_exchange_position(self, symbol: str) -> None:
        position = self._get_position_risk(symbol)
        if abs(float(position.get("positionAmt", 0) or 0)) > 0:
            raise BinanceLiveTradingError(f"{symbol} already has an exchange position")

    def _assert_account_capacity(self, new_notional_usdt: float) -> None:
        account = self._signed_request("GET", "/fapi/v2/account", {})
        available_balance = float(account.get("availableBalance", 0) or 0)
        positions = account.get("positions", [])
        current_total_notional = sum(abs(float(item.get("notional", 0) or 0)) for item in positions)
        if available_balance < self.settings.live_min_free_balance_usdt:
            raise BinanceLiveTradingError("free balance buffer is too low for live trading")
        if current_total_notional + new_notional_usdt > self.settings.live_max_total_notional_usdt:
            raise BinanceLiveTradingError("live total notional limit would be exceeded")

    def _configure_symbol(self, symbol: str) -> None:
        if not self._position_mode_configured:
            response = self._signed_request(
                "POST",
                "/fapi/v1/positionSide/dual",
                {"dualSidePosition": "false"},
                tolerate_errors=True,
            )
            if response != {"ignored": True}:
                self._position_mode_configured = True
            else:
                self._position_mode_configured = True
        if symbol not in self._margin_configured_symbols:
            response = self._signed_request(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": symbol, "marginType": self.settings.binance_margin_type},
                tolerate_errors=True,
            )
            if response == {"ignored": True} or isinstance(response, dict):
                self._margin_configured_symbols.add(symbol)
        if symbol not in self._leverage_configured_symbols:
            response = self._signed_request(
                "POST",
                "/fapi/v1/leverage",
                {"symbol": symbol, "leverage": max(1, min(5, self.settings.binance_futures_leverage))},
                tolerate_errors=True,
            )
            if response == {"ignored": True} or isinstance(response, dict):
                self._leverage_configured_symbols.add(symbol)

    def _get_position_risk(self, symbol: str) -> dict[str, Any]:
        positions = self._signed_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        if isinstance(positions, list) and positions:
            return positions[0]
        if isinstance(positions, dict):
            return positions
        return {"positionAmt": 0, "markPrice": 0, "entryPrice": 0, "unRealizedProfit": 0}

    def _build_protection_diagnostic_snapshot(
        self,
        trade: SimulatedTrade,
        error: Exception | None,
        *,
        attempts: int,
    ) -> dict[str, Any]:
        open_orders: list[dict[str, Any]] = []
        open_algo_orders: list[dict[str, Any]] = []
        position_risk: dict[str, Any] = {}
        snapshot_errors: list[str] = []

        try:
            open_orders = self._list_open_orders(trade.symbol)
        except Exception as exc:  # pragma: no cover - best-effort diagnostics
            snapshot_errors.append(f"open_orders_snapshot_failed: {exc}")

        try:
            open_algo_orders = self._list_open_algo_orders(trade.symbol)
        except Exception as exc:  # pragma: no cover - best-effort diagnostics
            snapshot_errors.append(f"open_algo_orders_snapshot_failed: {exc}")

        try:
            position_risk = self._get_position_risk(trade.symbol)
        except Exception as exc:  # pragma: no cover - best-effort diagnostics
            snapshot_errors.append(f"position_risk_snapshot_failed: {exc}")

        snapshot = {
            "symbol": trade.symbol,
            "direction": trade.direction,
            "entry_mode": trade.entry_mode,
            "attempts": attempts,
            "error": str(error) if error else None,
            "position_risk": position_risk,
            "open_orders": open_orders,
            "open_algo_orders": open_algo_orders,
            "snapshot_errors": snapshot_errors,
        }
        if isinstance(error, BinanceLiveTradingError) and error.context:
            snapshot["inner_error_context"] = error.context
        return snapshot

    @staticmethod
    def _algo_order_type(order: dict[str, Any]) -> str | None:
        return order.get("orderType") or order.get("type")

    def _get_mark_price(self, symbol: str) -> float:
        payload = self._public_request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(payload.get("markPrice", 0) or 0)

    def _get_symbol_rules(self, symbol: str) -> dict[str, float]:
        cached = self._exchange_rules.get(symbol)
        if cached:
            return cached
        exchange_info = self._public_request("GET", "/fapi/v1/exchangeInfo", {})
        for item in exchange_info.get("symbols", []):
            if item.get("symbol") != symbol:
                continue
            rules = {"step_size": 0.001, "tick_size": 0.01, "min_qty": 0.0, "min_notional": 5.0}
            rules["market_step_size"] = rules["step_size"]
            rules["quantity_precision"] = float(item.get("quantityPrecision", 8) or 8)
            for filt in item.get("filters", []):
                if filt.get("filterType") == "LOT_SIZE":
                    rules["step_size"] = float(filt.get("stepSize", 0.001) or 0.001)
                    rules["min_qty"] = float(filt.get("minQty", 0) or 0)
                elif filt.get("filterType") == "MARKET_LOT_SIZE":
                    rules["market_step_size"] = float(filt.get("stepSize", 0.001) or 0.001)
                    rules["min_qty"] = max(rules["min_qty"], float(filt.get("minQty", 0) or 0))
                elif filt.get("filterType") == "PRICE_FILTER":
                    rules["tick_size"] = float(filt.get("tickSize", 0.01) or 0.01)
                elif filt.get("filterType") in {"MIN_NOTIONAL", "NOTIONAL"}:
                    rules["min_notional"] = float(
                        filt.get("notional") or filt.get("minNotional") or 5.0
                    )
            self._exchange_rules[symbol] = rules
            return rules
        raise BinanceLiveTradingError(f"unable to find exchange rules for {symbol}")

    def _calculate_quantity(
        self,
        symbol: str,
        notional_usdt: float,
        price: float,
        rules: dict[str, float],
    ) -> str:
        if price <= 0:
            raise BinanceLiveTradingError(f"invalid mark price for {symbol}")
        target_notional = max(notional_usdt, rules["min_notional"] * 1.05)
        qty = target_notional / price
        if qty < rules["min_qty"]:
            qty = rules["min_qty"]
        qty_str = self._round_quantity(
            qty,
            rules.get("market_step_size", rules["step_size"]),
            int(rules.get("quantity_precision", 8)),
        )
        qty_float = float(qty_str)
        if qty_float <= 0:
            raise BinanceLiveTradingError(f"calculated quantity for {symbol} is zero")
        if qty_float * price > self.settings.max_position_notional_usdt * 1.02:
            raise BinanceLiveTradingError(f"{symbol} order would exceed max position notional")
        return qty_str

    def _public_request(self, method: str, path: str, params: dict[str, Any]) -> Any:
        return self._request(method, path, params, signed=False, tolerate_errors=False)

    def _signed_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        tolerate_errors: bool = False,
    ) -> Any:
        return self._request(method, path, params, signed=True, tolerate_errors=tolerate_errors)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        *,
        signed: bool,
        tolerate_errors: bool,
    ) -> Any:
        headers = {}
        last_error: Exception | None = None
        for attempt in range(2 if signed else 1):
            request_params = dict(params)
            if signed:
                if attempt == 0:
                    self._sync_server_time()
                else:
                    self._sync_server_time(force=True)
                request_params["timestamp"] = int(time.time() * 1000) + self._server_time_offset_ms
                request_params["recvWindow"] = 10000
                query = urlencode(request_params, doseq=True)
                signature = hmac.new(
                    (self.settings.binance_api_secret or "").encode("utf-8"),
                    query.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                request_params["signature"] = signature
                headers["X-MBX-APIKEY"] = self.settings.binance_api_key or ""

            try:
                return self._request_with_fallback(method, path, request_params, headers)
            except BinanceLiveTradingError as exc:
                last_error = exc
                if not signed or not self._should_retry_signed_request(exc):
                    if tolerate_errors:
                        ignored = self._maybe_ignore_configuration_error(path, exc)
                        if ignored is not None:
                            return ignored
                        return {}
                    raise
                continue
            except Exception as exc:
                last_error = exc
                if tolerate_errors:
                    return {}
                raise

        if tolerate_errors:
            return {}
        if last_error is not None:
            raise last_error
        raise BinanceLiveTradingError("binance live request failed")

    def _request_with_fallback(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        errors: list[Exception] = []
        for proxy in [None, self.settings.binance_proxy_url if self.settings.binance_proxy_fallback_enabled else None]:
            if proxy is None and errors:
                continue
            client_kwargs: dict[str, Any] = {"timeout": self.timeout, "headers": headers}
            if proxy:
                client_kwargs["proxy"] = proxy
            try:
                with httpx.Client(**client_kwargs) as client:
                    response = client.request(method, f"{self.base_url}{path}", params=params)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as exc:
                errors.append(
                    BinanceLiveTradingError(
                        self._format_http_error(exc.response)
                    )
                )
                continue
            except Exception as exc:
                errors.append(exc)
                continue
        if errors:
            raise BinanceLiveTradingError(str(errors[-1]))
        raise BinanceLiveTradingError("binance live request failed")

    def _sync_server_time(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and self._server_time_synced_at and now - self._server_time_synced_at < 60:
            return
        payload = self._request_with_fallback("GET", "/fapi/v1/time", {}, {})
        server_time = int(payload.get("serverTime", int(time.time() * 1000)))
        self._server_time_offset_ms = server_time - int(time.time() * 1000)
        self._server_time_synced_at = now

    @staticmethod
    def _should_retry_signed_request(exc: BinanceLiveTradingError) -> bool:
        message = str(exc)
        retry_markers = (
            "-1021",
            "-1022",
            "recvwindow",
            "timestamp",
        )
        return any(marker in message.lower() for marker in retry_markers)

    @staticmethod
    def _is_protection_conflict_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "-4130" in message or "closeposition in the direction is existing" in message

    @staticmethod
    def _format_http_error(response: httpx.Response) -> str:
        body = response.text.strip()
        if not body:
            body = response.reason_phrase
        return (
            f"binance http {response.status_code} for {response.request.url}: {body}"
        )

    @staticmethod
    def _extract_binance_error_details(message: str) -> tuple[int | None, str]:
        code_match = re.search(r'"code"\s*:\s*(-?\d+)', message)
        msg_match = re.search(r'"msg"\s*:\s*"([^"]+)"', message)
        code = int(code_match.group(1)) if code_match else None
        msg = msg_match.group(1) if msg_match else message
        return code, msg

    def _maybe_ignore_configuration_error(
        self,
        path: str,
        exc: BinanceLiveTradingError,
    ) -> dict[str, Any] | None:
        code, msg = self._extract_binance_error_details(str(exc))
        normalized = msg.lower()
        if path == "/fapi/v1/positionSide/dual":
            if code in {-4059, -4061} or "no need to change position side" in normalized:
                return {"ignored": True}
        if path == "/fapi/v1/marginType":
            if code in {-4046} or "no need to change margin type" in normalized:
                return {"ignored": True}
        if path == "/fapi/v1/leverage":
            if "leverage not modified" in normalized or "no need to change leverage" in normalized:
                return {"ignored": True}
        return None

    @staticmethod
    def _round_down(value: float, step: float) -> str:
        if step <= 0:
            return f"{value:.8f}"
        decimal_value = Decimal(str(value))
        decimal_step = Decimal(str(step))
        rounded = (decimal_value // decimal_step) * decimal_step
        return format(rounded.normalize(), "f")

    @staticmethod
    def _round_quantity(value: float, step: float, precision: int) -> str:
        rounded = BinanceLiveTrader._round_down(value, step)
        quantized = Decimal(rounded)
        if precision < 0:
            precision = 0
        if precision == 0:
            quantized = quantized.quantize(Decimal("1"), rounding=ROUND_DOWN)
        else:
            quantized = quantized.quantize(Decimal("1").scaleb(-precision), rounding=ROUND_DOWN)
        return format(quantized.normalize(), "f")
