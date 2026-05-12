from typing import Any, Protocol

from app.config import Settings, get_settings
from app.data.binance_client import BinanceClient


class MarketDataAdapter(Protocol):
    async def get_liquidation_data(
        self, symbol: str, interval: str = "1h", limit: int = 100
    ) -> dict[str, Any]: ...

    async def get_oi_distribution(
        self, symbol: str, interval: str = "5m", limit: int = 1
    ) -> dict[str, Any]: ...

    async def get_fund_flow_metrics(
        self, symbol: str, interval: str = "5m", limit: int = 1
    ) -> dict[str, Any]: ...


class CoinglassApiPlaceholder:
    """Reserved adapter for future Coinglass integration.

    The MVP defaults to Binance so the project can run without a Coinglass API key.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    async def get_liquidation_data(
        self, symbol: str, interval: str = "1h", limit: int = 100
    ) -> dict[str, Any]:
        return self._not_configured("liquidation_data", symbol, interval)

    async def get_oi_distribution(
        self, symbol: str, interval: str = "5m", limit: int = 1
    ) -> dict[str, Any]:
        return self._not_configured("oi_distribution", symbol, interval)

    async def get_fund_flow_metrics(
        self, symbol: str, interval: str = "5m", limit: int = 1
    ) -> dict[str, Any]:
        return self._not_configured("fund_flow_metrics", symbol, interval)

    @staticmethod
    def _not_configured(kind: str, symbol: str, interval: str) -> dict[str, Any]:
        return {
            "source": "coinglass",
            "kind": kind,
            "symbol": symbol,
            "data": [],
            "meta": {
                "interval": interval,
                "status": "not_configured",
                "message": "Coinglass adapter is reserved; set MARKET_DATA_SOURCE=binance for MVP.",
            },
        }


class CoinglassClient:
    """Backward-compatible market data entrypoint.

    Existing callers can keep importing CoinglassClient while the default data source
    is Binance. Later, MARKET_DATA_SOURCE can switch to coinglass without changing
    upper-layer method names.
    """

    def __init__(self, settings: Settings | None = None, adapter: MarketDataAdapter | None = None) -> None:
        self.settings = settings or get_settings()
        self.adapter = adapter or self._build_adapter()

    def _build_adapter(self) -> MarketDataAdapter:
        source = self.settings.market_data_source.lower()
        if source == "coinglass":
            return CoinglassApiPlaceholder(self.settings.coinglass_api_key)
        return BinanceClient(
            futures_base_url=self.settings.binance_base_url,
            spot_base_url=self.settings.binance_spot_base_url,
            proxy_url=self.settings.binance_proxy_url,
            proxy_fallback_enabled=self.settings.binance_proxy_fallback_enabled,
        )

    async def get_liquidation_data(
        self, symbol: str, interval: str = "1h", limit: int = 100
    ) -> dict[str, Any]:
        return await self.adapter.get_liquidation_data(symbol, interval, limit)

    async def get_oi_distribution(
        self, symbol: str, interval: str = "5m", limit: int = 1
    ) -> dict[str, Any]:
        return await self.adapter.get_oi_distribution(symbol, interval, limit)

    async def get_fund_flow_metrics(
        self, symbol: str, interval: str = "5m", limit: int = 1
    ) -> dict[str, Any]:
        return await self.adapter.get_fund_flow_metrics(symbol, interval, limit)
