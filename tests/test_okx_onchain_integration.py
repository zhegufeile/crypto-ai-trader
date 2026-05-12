import json
from pathlib import Path
import asyncio

import pytest

from app.config import Settings
from app.data.market_collector import MarketCollector
from app.data.okx_client import OKXClient


class FakeBinanceClient:
    async def get_24h_tickers(self):
        return [
            {
                "symbol": "BTCUSDT",
                "lastPrice": "65000",
                "volume": "1000",
                "quoteVolume": "500000000",
                "priceChangePercent": "2.5",
            },
            {
                "symbol": "PNKSTRUSDT",
                "lastPrice": "1.2",
                "volume": "1000",
                "quoteVolume": "120000000",
                "priceChangePercent": "6.0",
            },
        ]

    async def get_open_interest(self, symbol: str):
        return {"openInterest": "1000", "time": 1}

    async def get_premium_index(self, symbol: str):
        return {"lastFundingRate": "0.0001", "time": 1}

    async def get_long_short_ratio(self, symbol: str, period: str = "5m", limit: int = 1):
        return [{"longShortRatio": "1.1", "timestamp": 1}]

    async def get_taker_buy_sell_ratio(self, symbol: str, period: str = "5m", limit: int = 1):
        return [{"buySellRatio": "1.15", "timestamp": 1}]


def test_okx_client_loads_signal_snapshot(tmp_path: Path):
    path = tmp_path / "signals.json"
    path.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "token_symbol": "PNKSTR",
                        "signalScore": 0.72,
                        "walletCount": 4,
                        "buyAmountUsd": 85000,
                        "soldRatioPercent": 22,
                        "walletType": ["Smart Money", "KOL"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    signal_map = asyncio.run(OKXClient(signal_snapshot_file=path).get_symbol_signal_map(["PNKSTRUSDT"]))

    assert signal_map["PNKSTR"]["signal_score"] == 0.72
    assert signal_map["PNKSTR"]["wallet_count"] == 4


def test_okx_client_loads_risk_snapshot(tmp_path: Path):
    path = tmp_path / "risks.json"
    path.write_text(
        json.dumps(
            {
                "risks": [
                    {
                        "symbol": "SCAM",
                        "risk_level": "CRITICAL",
                        "risk_tags": ["honeypot"],
                        "honeypot": True,
                        "is_safe_buy": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    risk_map = asyncio.run(OKXClient(risk_snapshot_file=path).get_symbol_risk_map(["SCAMUSDT"]))

    assert risk_map["SCAM"]["honeypot"] is True
    assert risk_map["SCAM"]["is_safe_buy"] is False


@pytest.mark.asyncio
async def test_market_collector_applies_onchain_signal_boost(tmp_path: Path):
    path = tmp_path / "signals.json"
    path.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "symbol": "PNKSTR",
                        "signal_score": 0.78,
                        "wallet_count": 5,
                        "buy_amount_usd": 125000,
                        "sold_ratio_percent": 18,
                        "wallet_types": ["smart_money", "kol"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        min_volume_usdt=1000,
        max_candidates=5,
        enable_onchain_signal_boost=True,
        onchain_signal_snapshot_file=str(path),
    )
    collector = MarketCollector(settings=settings, client=FakeBinanceClient())

    candidates = await collector.collect_candidates()

    pnkstr = next(item for item in candidates if item.snapshot.symbol == "PNKSTRUSDT")
    assert pnkstr.snapshot.onchain_signal_score > 0
    assert "onchain_signal" in pnkstr.tags
    assert pnkstr.hard_score > 80


@pytest.mark.asyncio
async def test_market_collector_hard_downgrades_honeypot(tmp_path: Path):
    signal_path = tmp_path / "signals.json"
    signal_path.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "symbol": "PNKSTR",
                        "signal_score": 0.9,
                        "wallet_count": 5,
                        "buy_amount_usd": 125000,
                        "sold_ratio_percent": 10,
                        "wallet_types": ["smart_money"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    risk_path = tmp_path / "risks.json"
    risk_path.write_text(
        json.dumps(
            {
                "risks": [
                    {
                        "symbol": "PNKSTR",
                        "risk_level": "CRITICAL",
                        "risk_tags": ["honeypot"],
                        "honeypot": True,
                        "is_safe_buy": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        min_volume_usdt=1000,
        max_candidates=5,
        enable_onchain_signal_boost=True,
        onchain_signal_snapshot_file=str(signal_path),
        onchain_risk_snapshot_file=str(risk_path),
    )
    collector = MarketCollector(settings=settings, client=FakeBinanceClient())

    candidates = await collector.collect_candidates()

    pnkstr = next(item for item in candidates if item.snapshot.symbol == "PNKSTRUSDT")
    assert pnkstr.snapshot.onchain_honeypot is True
    assert pnkstr.snapshot.onchain_is_safe_buy is False
    assert pnkstr.hard_score == 0
