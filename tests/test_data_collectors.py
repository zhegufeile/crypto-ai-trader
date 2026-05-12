from app.config import Settings
from app.data.coinglass_client import CoinglassClient
import pytest


class FakeAdapter:
    async def get_liquidation_data(self, symbol: str, interval: str = "1h", limit: int = 100):
        return {"source": "binance", "symbol": symbol, "data": [], "meta": {"interval": interval}}

    async def get_oi_distribution(self, symbol: str, interval: str = "5m", limit: int = 1):
        return {"source": "binance", "symbol": symbol, "data": [], "meta": {"interval": interval}}

    async def get_fund_flow_metrics(self, symbol: str, interval: str = "5m", limit: int = 1):
        return {"source": "binance", "symbol": symbol, "data": [], "meta": {"interval": interval}}


@pytest.mark.asyncio
async def test_coinglass_client_keeps_public_methods():
    client = CoinglassClient(settings=Settings(), adapter=FakeAdapter())

    result = await client.get_oi_distribution("BTCUSDT")

    assert result["source"] == "binance"
    assert result["symbol"] == "BTCUSDT"
