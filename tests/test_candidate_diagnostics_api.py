from fastapi.testclient import TestClient

from app.data.schema import Candidate, MarketSnapshot
from app.knowledge.distiller import StrategyCard
from app.main import app


class FakeCollector:
    async def collect_candidates(self):
        return [
            Candidate(
                snapshot=MarketSnapshot(
                    symbol="PNKSTRUSDT",
                    price=1.2,
                    price_change_pct_24h=6.0,
                    quote_volume_24h=120_000_000,
                    oi=1000,
                    funding_rate=0.0001,
                    long_short_ratio=1.1,
                    taker_buy_sell_ratio=1.15,
                    btc_trend="up",
                    market_regime="trend_or_acceleration",
                    reversal_stage="first_reversal",
                    relative_strength_score=0.8,
                    retest_quality_score=0.7,
                    follow_through_score=0.75,
                    onchain_signal_score=0.9,
                    onchain_wallet_count=4,
                ),
                hard_score=85,
                tags=["relative_strength_leader"],
                reasons=["strong candidate"],
            ),
            Candidate(
                snapshot=MarketSnapshot(
                    symbol="SCAMUSDT",
                    price=0.01,
                    price_change_pct_24h=20.0,
                    quote_volume_24h=80_000_000,
                    oi=500,
                    funding_rate=0.0002,
                    long_short_ratio=1.05,
                    taker_buy_sell_ratio=1.1,
                    btc_trend="up",
                    market_regime="trend_or_acceleration",
                    reversal_stage="trend",
                    relative_strength_score=0.7,
                    retest_quality_score=0.65,
                    follow_through_score=0.7,
                    onchain_honeypot=True,
                    onchain_is_safe_buy=False,
                    onchain_risk_level="CRITICAL",
                    onchain_liquidity_usd=5000,
                ),
                hard_score=90,
                reasons=["risky candidate"],
            ),
        ]


class FailingCollector:
    async def collect_candidates(self):
        raise RuntimeError("binance unavailable")


class FakeTradeRepo:
    def __init__(self, session):
        self.session = session

    def list_open_trades(self):
        return []


class FakeStrategyStore:
    def list_cards(self):
        return [
            StrategyCard(
                name="pnk_core",
                description="core card",
                creator="tester",
                confidence_bias=0.2,
                preferred_symbols=["PNKSTRUSDT"],
                entry_conditions=["breakout", "relative_strength_leader"],
                exit_conditions=["target_reached"],
                invalidation_conditions=["failed_follow_through_after_retest"],
                risk_notes=["respect core structure"],
                strategy_tier="core",
                tier_score=96.0,
            ),
            StrategyCard(
                name="pnk_watch",
                description="watch card",
                creator="tester",
                confidence_bias=0.2,
                preferred_symbols=["PNKSTRUSDT"],
                entry_conditions=["breakout"],
                exit_conditions=["target_reached"],
                risk_notes=["watchlist confirmation only"],
                strategy_tier="watchlist",
                tier_score=20.0,
            ),
        ]


def test_candidate_diagnostics_api_returns_tradeable_and_blocked(monkeypatch):
    monkeypatch.setattr("app.api.routes_diagnostics.MarketCollector", lambda settings=None: FakeCollector())
    monkeypatch.setattr("app.api.routes_diagnostics.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.core.signal_engine.StrategyStore", FakeStrategyStore)

    client = TestClient(app)
    response = client.get("/diagnostics/candidates?limit=10&tier_mode=core-only")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["symbol"] == "PNKSTRUSDT"
    assert payload[0]["tradeable"] is True
    assert payload[0]["signal"] is not None
    assert payload[0]["strategy_tier_mode"] == "core-only"
    assert payload[0]["strategy_matches"][0]["name"] == "pnk_core"
    assert payload[0]["strategy_matches"][0]["tier"] == "core"
    blocked = next(item for item in payload if item["symbol"] == "SCAMUSDT")
    assert blocked["tradeable"] is False
    assert "onchain security flags this token as honeypot" in blocked["risk"]["reasons"]


def test_candidate_diagnostics_api_returns_empty_list_when_market_collection_fails(monkeypatch):
    monkeypatch.setattr("app.api.routes_diagnostics.MarketCollector", lambda settings=None: FailingCollector())
    monkeypatch.setattr("app.api.routes_diagnostics.TradeRepository", FakeTradeRepo)

    client = TestClient(app)
    response = client.get("/diagnostics/candidates?limit=10")

    assert response.status_code == 200
    assert response.json() == []
