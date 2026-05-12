from datetime import UTC, datetime
from typing import AsyncIterator
from typing import Any

import httpx
from contextlib import asynccontextmanager


class BinanceRequestSession:
    def __init__(
        self,
        direct_client: httpx.AsyncClient,
        proxy_client: httpx.AsyncClient | None,
        futures_base_url: str,
        spot_base_url: str,
    ) -> None:
        self.direct_client = direct_client
        self.proxy_client = proxy_client
        self.futures_base_url = futures_base_url
        self.spot_base_url = spot_base_url

    async def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        last_error: httpx.HTTPError | None = None
        try:
            response = await self.direct_client.get(url, params=params)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_error = exc

        if self.proxy_client is not None:
            response = await self.proxy_client.get(url, params=params)
            response.raise_for_status()
            return response

        if last_error is not None:
            raise last_error
        raise RuntimeError("binance request session failed without an http error")


class BinanceClient:
    """Small Binance Futures data client for MVP market scanning."""

    def __init__(
        self,
        futures_base_url: str = "https://fapi.binance.com",
        spot_base_url: str = "https://api.binance.com",
        timeout: float = 10,
        proxy_url: str | None = None,
        proxy_fallback_enabled: bool = True,
    ) -> None:
        self.futures_base_url = futures_base_url.rstrip("/")
        self.spot_base_url = spot_base_url.rstrip("/")
        self.timeout = timeout
        self.proxy_url = proxy_url
        self.proxy_fallback_enabled = proxy_fallback_enabled

    @asynccontextmanager
    async def session(self) -> AsyncIterator["BinanceRequestSession"]:
        direct_client = httpx.AsyncClient(timeout=self.timeout)
        proxy_client = (
            httpx.AsyncClient(timeout=self.timeout, proxy=self.proxy_url)
            if self.proxy_url and self.proxy_fallback_enabled
            else None
        )
        try:
            yield BinanceRequestSession(direct_client, proxy_client, self.futures_base_url, self.spot_base_url)
        finally:
            await direct_client.aclose()
            if proxy_client is not None:
                await proxy_client.aclose()

    async def _get(
        self,
        base_url: str,
        path: str,
        params: dict[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> Any:
        if client is not None:
            response = await client.get(f"{base_url}{path}", params=params)
            response.raise_for_status()
            return response.json()

        last_error: httpx.HTTPError | None = None
        attempts: list[str | None] = [None]
        if self.proxy_url and self.proxy_fallback_enabled:
            attempts.append(self.proxy_url)

        for proxy in attempts:
            try:
                client_kwargs: dict[str, Any] = {"timeout": self.timeout}
                if proxy:
                    client_kwargs["proxy"] = proxy
                async with httpx.AsyncClient(**client_kwargs) as client:
                    response = await client.get(f"{base_url}{path}", params=params)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("binance request failed without an http error")

    async def get_24h_tickers(self, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
        return await self._get(self.futures_base_url, "/fapi/v1/ticker/24hr", client=client)

    async def get_premium_index(self, symbol: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        return await self._get(self.futures_base_url, "/fapi/v1/premiumIndex", {"symbol": symbol}, client=client)

    async def get_open_interest(self, symbol: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        return await self._get(self.futures_base_url, "/fapi/v1/openInterest", {"symbol": symbol}, client=client)

    async def get_long_short_ratio(
        self, symbol: str, period: str = "5m", limit: int = 1, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        return await self._get(
            self.futures_base_url,
            "/futures/data/globalLongShortAccountRatio",
            {"symbol": symbol, "period": period, "limit": limit},
            client=client,
        )

    async def get_taker_buy_sell_ratio(
        self, symbol: str, period: str = "5m", limit: int = 1, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        return await self._get(
            self.futures_base_url,
            "/futures/data/takerlongshortRatio",
            {"symbol": symbol, "period": period, "limit": limit},
            client=client,
        )

    async def get_klines(
        self, symbol: str, interval: str = "5m", limit: int = 100, client: httpx.AsyncClient | None = None
    ) -> list[list[Any]]:
        return await self._get(
            self.futures_base_url,
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
            client=client,
        )

    async def get_force_orders(
        self, symbol: str | None = None, limit: int = 100, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return await self._get(self.futures_base_url, "/fapi/v1/allForceOrders", params, client=client)

    async def get_liquidation_data(
        self, symbol: str, interval: str = "1h", limit: int = 100
    ) -> dict[str, Any]:
        orders = await self.get_force_orders(symbol=symbol, limit=limit)
        data = [
            {
                "symbol": item.get("symbol", symbol),
                "side": item.get("side"),
                "price": float(item.get("price", 0) or 0),
                "qty": float(item.get("origQty", 0) or 0),
                "notional": float(item.get("price", 0) or 0) * float(item.get("origQty", 0) or 0),
                "time": item.get("time"),
            }
            for item in orders
        ]
        return self._wrap("liquidation_data", symbol, interval, data)

    async def get_oi_distribution(
        self, symbol: str, interval: str = "5m", limit: int = 1
    ) -> dict[str, Any]:
        oi = await self.get_open_interest(symbol)
        ratios = await self.get_long_short_ratio(symbol, period=interval, limit=limit)
        latest_ratio = ratios[-1] if ratios else {}
        data = [
            {
                "symbol": symbol,
                "open_interest": float(oi.get("openInterest", 0) or 0),
                "long_short_ratio": float(latest_ratio.get("longShortRatio", 0) or 0),
                "long_account": float(latest_ratio.get("longAccount", 0) or 0),
                "short_account": float(latest_ratio.get("shortAccount", 0) or 0),
                "time": oi.get("time") or latest_ratio.get("timestamp"),
            }
        ]
        return self._wrap("oi_distribution", symbol, interval, data)

    async def get_fund_flow_metrics(
        self, symbol: str, interval: str = "5m", limit: int = 1
    ) -> dict[str, Any]:
        premium = await self.get_premium_index(symbol)
        taker = await self.get_taker_buy_sell_ratio(symbol, period=interval, limit=limit)
        latest_taker = taker[-1] if taker else {}
        data = [
            {
                "symbol": symbol,
                "funding_rate": float(premium.get("lastFundingRate", 0) or 0),
                "mark_price": float(premium.get("markPrice", 0) or 0),
                "index_price": float(premium.get("indexPrice", 0) or 0),
                "taker_buy_sell_ratio": float(latest_taker.get("buySellRatio", 0) or 0),
                "buy_volume": float(latest_taker.get("buyVol", 0) or 0),
                "sell_volume": float(latest_taker.get("sellVol", 0) or 0),
                "time": premium.get("time") or latest_taker.get("timestamp"),
            }
        ]
        return self._wrap("fund_flow_metrics", symbol, interval, data)

    @staticmethod
    def _wrap(kind: str, symbol: str, interval: str, data: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "source": "binance",
            "kind": kind,
            "symbol": symbol,
            "data": data,
            "meta": {
                "interval": interval,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }
