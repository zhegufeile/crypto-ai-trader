from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.simulator import SimulatedTrade
from app.main import app
from app.storage.models import SimTradeRecord
from app.storage.repositories import TradeRepository


class FakeTradeRepo:
    def __init__(self, session):
        self.session = session

    def list_open_trades(self):
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
                remaining_notional_usdt=100,
                initial_stop_loss=95,
                current_stop_loss=95,
                tp1_price=105,
                tp2_price=110,
                opened_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                management_plan=["hold the stop"],
            )
        ]

    def list_all_trades(self, limit: int = 100):
        trade = self.list_open_trades()[0]
        closed = trade.model_copy(update={"id": "closed-1", "status": "closed", "pnl_usdt": 5, "realized_pnl_usdt": 5})
        return [trade, closed]


class FakeJournalRepo:
    def __init__(self, session):
        self.session = session

    def list_events(self, limit: int = 100):
        return [
            {
                "id": 1,
                "trade_id": "open-1",
                "symbol": "BTCUSDT",
                "event_type": "trade_opened",
                "status": "info",
                "message": "simulated trade opened",
                "details": "{}",
                "created_at": datetime.now(UTC),
            }
        ]

    def delete_all(self):
        return 5


class FakeResetTradeRepo(FakeTradeRepo):
    def delete_all(self):
        return 3


class FakeResetSignalRepo:
    def __init__(self, session):
        self.session = session

    def delete_all(self):
        return 7


def test_positions_api_supports_include_closed(monkeypatch):
    monkeypatch.setattr("app.api.routes_positions.TradeRepository", FakeTradeRepo)

    client = TestClient(app)

    open_only = client.get("/positions")
    assert open_only.status_code == 200
    assert len(open_only.json()) == 1

    include_closed = client.get("/positions?include_closed=true")
    assert include_closed.status_code == 200
    assert len(include_closed.json()) == 2


def test_positions_journal_api_returns_trade_events(monkeypatch):
    monkeypatch.setattr("app.api.routes_positions.TradeJournalRepository", FakeJournalRepo)

    client = TestClient(app)
    response = client.get("/positions/journal?limit=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["event_type"] == "trade_opened"
    assert payload[0]["symbol"] == "BTCUSDT"


def test_positions_reset_api_clears_runtime_state(monkeypatch):
    monkeypatch.setattr("app.api.routes_positions.SignalRepository", FakeResetSignalRepo)
    monkeypatch.setattr("app.api.routes_positions.TradeRepository", FakeResetTradeRepo)
    monkeypatch.setattr("app.api.routes_positions.TradeJournalRepository", FakeJournalRepo)

    client = TestClient(app)
    response = client.post("/positions/reset")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["signals_deleted"] == 7
    assert payload["positions_deleted"] == 3
    assert payload["journal_deleted"] == 5


def test_trade_repository_handles_legacy_null_updated_at():
    record = SimTradeRecord(
        id="legacy-1",
        symbol="ETHUSDT",
        direction="long",
        structure="pullback",
        entry=100,
        stop_loss=95,
        take_profit=112,
        notional_usdt=100,
        remaining_notional_usdt=100,
        initial_stop_loss=95,
        current_stop_loss=95,
        tp1_price=105,
        tp2_price=110,
        status="open",
        opened_at=datetime.now(UTC),
    )
    record.updated_at = None

    trade = TradeRepository._to_trade_model(record)

    assert trade.updated_at is not None
    assert trade.opened_at is not None


def test_trade_repository_normalizes_naive_sqlite_datetimes():
    naive_opened_at = datetime.now().replace(microsecond=0)
    record = SimTradeRecord(
        id="legacy-naive-1",
        symbol="XAGUSDT",
        direction="long",
        structure="breakout",
        entry=100,
        stop_loss=95,
        take_profit=112,
        notional_usdt=100,
        remaining_notional_usdt=100,
        initial_stop_loss=95,
        current_stop_loss=95,
        tp1_price=105,
        tp2_price=110,
        status="pending_entry",
        opened_at=naive_opened_at,
        updated_at=naive_opened_at,
    )

    trade = TradeRepository._to_trade_model(record)

    assert trade.opened_at.tzinfo is not None
    assert trade.updated_at.tzinfo is not None
