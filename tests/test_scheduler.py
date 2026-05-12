import pytest

from app.config import Settings
from app.core.scheduler import run_scan_once


class FakeCollector:
    async def collect_candidates(self):
        return []


class FailingCollector:
    async def collect_candidates(self):
        raise RuntimeError("binance unavailable")


class FakeSignalRepo:
    def __init__(self, session):
        self.session = session

    def save_signal(self, signal):
        return signal


class FakeTradeRepo:
    def __init__(self, session):
        self.session = session

    def list_open_trades(self):
        return []

    def list_recent_closed_trades(self):
        return []

    def save_trade(self, trade):
        return trade

    def update_trade(self, trade):
        return trade


class FakeJournalRepo:
    def __init__(self, session):
        self.session = session
        self.events = []

    def count_recent_actions(self, window_minutes: int, event_types=None):
        return 99

    def log_event(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class FakeSignalEngine:
    def __init__(self, settings=None):
        self.settings = settings

    def generate_signals(self, *args, **kwargs):
        raise AssertionError("generate_signals should not run after circuit breaker trips")


class FakeExecutionEngine:
    def __init__(self, settings=None):
        self.settings = settings

    def manage_simulated(self, trade, snapshot):
        return trade

    def execute_simulated(self, signal, risk_decision):
        return None


@pytest.mark.asyncio
async def test_run_scan_once_trips_trade_loop_circuit_breaker(monkeypatch):
    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollector())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", FakeJournalRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngine)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", FakeExecutionEngine)

    result = await run_scan_once(
        session=object(),
        settings=Settings(max_trade_actions_in_window=6, trade_action_circuit_window_minutes=15),
    )

    assert result["circuit_breaker"] is True
    assert result["signals"] == 0
    assert result["simulated_trades"] == 0


@pytest.mark.asyncio
async def test_run_scan_once_returns_structured_error_when_market_collection_fails(monkeypatch):
    journal_repo = FakeJournalRepo(session=object())

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FailingCollector())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngine)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", FakeExecutionEngine)

    result = await run_scan_once(session=object(), settings=Settings())

    assert result["status"] == "error"
    assert result["stage"] == "collect_candidates"
    assert result["signals"] == 0
    assert journal_repo.events[-1]["event_type"] == "scan_failed"
