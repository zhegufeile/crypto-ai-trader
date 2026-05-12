import httpx
import pytest

from app.data.binance_client import BinanceClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.mark.asyncio
async def test_binance_client_falls_back_to_proxy(monkeypatch):
    calls: list[str | None] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout, proxy=None):
            self.proxy = proxy

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            calls.append(self.proxy)
            if self.proxy is None:
                raise httpx.ConnectError("direct failed")
            return FakeResponse([{"symbol": "BTCUSDT"}])

    monkeypatch.setattr("app.data.binance_client.httpx.AsyncClient", FakeAsyncClient)

    client = BinanceClient(proxy_url="http://127.0.0.1:10809", proxy_fallback_enabled=True)
    result = await client.get_24h_tickers()

    assert result == [{"symbol": "BTCUSDT"}]
    assert calls == [None, "http://127.0.0.1:10809"]


@pytest.mark.asyncio
async def test_binance_client_uses_direct_when_available(monkeypatch):
    calls: list[str | None] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout, proxy=None):
            self.proxy = proxy

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            calls.append(self.proxy)
            return FakeResponse([{"symbol": "ETHUSDT"}])

    monkeypatch.setattr("app.data.binance_client.httpx.AsyncClient", FakeAsyncClient)

    client = BinanceClient(proxy_url="http://127.0.0.1:10809", proxy_fallback_enabled=True)
    result = await client.get_24h_tickers()

    assert result == [{"symbol": "ETHUSDT"}]
    assert calls == [None]
