from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.simulator import SimulatedTrade
from app.config import Settings
from app.main import app


class FakeTradeRepo:
    def __init__(self, session):
        self.session = session

    def list_all_trades(self, limit: int = 1000):
        now = datetime.now(UTC)
        return [
            SimulatedTrade(
                id="open-1",
                symbol="BTCUSDT",
                direction="long",
                structure="breakout",
                entry=100,
                stop_loss=95,
                take_profit=112,
                notional_usdt=100,
                remaining_notional_usdt=80,
                initial_stop_loss=95,
                current_stop_loss=98,
                tp1_price=105,
                tp2_price=110,
                status="open",
                unrealized_pnl_usdt=12,
                realized_pnl_usdt=4,
                pnl_usdt=16,
                opened_at=now,
                updated_at=now,
                primary_strategy_name="derrrrrrq_generic",
                matched_strategy_names=["derrrrrrq_generic", "onchainos_smart_money_gate"],
            ),
            SimulatedTrade(
                id="closed-1",
                symbol="ETHUSDT",
                direction="short",
                structure="pullback",
                entry=50,
                stop_loss=52,
                take_profit=44,
                notional_usdt=100,
                remaining_notional_usdt=0,
                initial_stop_loss=52,
                current_stop_loss=52,
                tp1_price=48,
                tp2_price=46,
                status="closed",
                realized_pnl_usdt=25,
                pnl_usdt=25,
                opened_at=now - timedelta(hours=6),
                updated_at=now - timedelta(hours=1),
                closed_at=now - timedelta(hours=1),
                primary_strategy_name="derrrrrrq_generic",
                matched_strategy_names=["derrrrrrq_generic"],
            ),
        ]


class FakeFeeRepo:
    def __init__(self, session):
        self.session = session

    def sum_all(self):
        return 3.25

    def sum_since(self, cutoff):
        return 1.1


class FakeLiveTrader:
    def __init__(self, settings=None):
        self.settings = settings

    def _signed_request(self, method, path, params):
        return {
            "totalWalletBalance": "212.2832",
            "availableBalance": "92.1970",
            "totalUnrealizedProfit": "1.4321",
            "positions": [
                {"symbol": "BTCUSDT", "positionAmt": "0.01"},
                {"symbol": "ETHUSDT", "positionAmt": "0"},
            ],
        }


def test_account_summary_api_returns_simulation_metrics(monkeypatch):
    monkeypatch.setattr("app.api.routes_account.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.api.routes_account.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.api.routes_account.get_settings", lambda: Settings(use_simulation=True))

    client = TestClient(app)
    response = client.get("/account/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "simulation"
    assert payload["equity_usdt"] > 0
    assert payload["total_fees_usdt"] == 3.25
    assert payload["fees_24h_usdt"] == 1.1
    assert payload["open_positions"] == 1
    assert payload["closed_trades"] == 1
    assert payload["equity_curve"]
    assert payload["strategy_attribution"][0]["strategy_name"] == "derrrrrrq_generic"
    assert payload["strategy_attribution"][0]["total_pnl_usdt"] == 41.0
    assert payload["strategy_attribution"][0]["open_trades"] == 1
    assert payload["strategy_attribution"][0]["closed_trades"] == 1


def test_account_summary_api_returns_live_exchange_balances(monkeypatch):
    monkeypatch.setattr("app.api.routes_account.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.api.routes_account.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.api.routes_account.BinanceLiveTrader", FakeLiveTrader)
    monkeypatch.setattr("app.api.routes_account.get_settings", lambda: Settings(use_simulation=False, live_trading_enabled=True))

    client = TestClient(app)
    response = client.get("/account/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "live"
    assert payload["equity_usdt"] == 212.2832
    assert payload["available_balance_usdt"] == 92.197
    assert payload["unrealized_pnl_usdt"] == 1.4321
    assert payload["open_positions"] == 1
    assert payload["exchange_account_warning"] is None
    assert payload["strategy_attribution"][0]["strategy_name"] == "derrrrrrq_generic"
