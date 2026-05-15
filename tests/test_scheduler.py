import pytest
import logging

from app.config import Settings
from app.core.live_trader import BinanceLiveTradingError
from app.core.simulator import SimulatedTrade
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


class NonBlockingJournalRepo(FakeJournalRepo):
    def count_recent_actions(self, window_minutes: int, event_types=None):
        return 0


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


class FakeFeeRepo:
    def __init__(self, session):
        self.session = session
        self.fees = []

    def log_fee(self, **kwargs):
        self.fees.append(kwargs)
        return kwargs


class FailingExecutionEngine:
    def __init__(self, settings=None):
        self.settings = settings

    def manage_simulated(self, trade, snapshot):
        return trade

    def execute_simulated(self, signal, risk_decision):
        raise RuntimeError("live execution failed")


class ForceClosedExecutionEngine:
    def __init__(self, settings=None):
        self.settings = settings

    def manage_simulated(self, trade, snapshot):
        return trade

    def execute_simulated(self, signal, risk_decision):
        trade = SimulatedTrade(
            symbol=signal.symbol,
            direction=signal.direction.value,
            structure=signal.structure.value,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            notional_usdt=200,
            remaining_notional_usdt=0,
            initial_stop_loss=signal.stop_loss,
            current_stop_loss=signal.stop_loss,
            tp1_price=signal.entry * 1.01,
            tp2_price=signal.entry * 1.02,
            status="closed",
            realized_pnl_usdt=-1.2,
            fees_paid_usdt=0.16,
            exit_reason="entry was force-closed because exchange protection could not be verified",
        )
        raise BinanceLiveTradingError("protection failed", trade=trade)


class ForceClosedExecutionEngineWithContext:
    def __init__(self, settings=None):
        self.settings = settings

    def manage_simulated(self, trade, snapshot):
        return trade

    def execute_simulated(self, signal, risk_decision):
        trade = SimulatedTrade(
            symbol=signal.symbol,
            direction=signal.direction.value,
            structure=signal.structure.value,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            notional_usdt=200,
            remaining_notional_usdt=0,
            initial_stop_loss=signal.stop_loss,
            current_stop_loss=signal.stop_loss,
            tp1_price=signal.entry * 1.01,
            tp2_price=signal.entry * 1.02,
            status="closed",
            realized_pnl_usdt=-1.2,
            fees_paid_usdt=0.16,
            exit_reason="entry was force-closed because exchange protection could not be verified",
        )
        raise BinanceLiveTradingError(
            "protection failed",
            trade=trade,
            context={"symbol": signal.symbol, "open_algo_orders": [{"type": "STOP_MARKET"}]},
        )


@pytest.mark.asyncio
async def test_run_scan_once_trips_trade_loop_circuit_breaker(monkeypatch):
    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollector())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", FakeJournalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
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
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngine)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", FakeExecutionEngine)

    result = await run_scan_once(session=object(), settings=Settings())

    assert result["status"] == "error"
    assert result["stage"] == "collect_candidates"
    assert result["signals"] == 0
    assert journal_repo.events[-1]["event_type"] == "scan_failed"


class FakeCollectorWithCandidate:
    async def collect_candidates(self):
        from app.data.schema import Candidate, MarketSnapshot

        return [Candidate(snapshot=MarketSnapshot(symbol="BTCUSDT", price=100000, quote_volume_24h=1e9), hard_score=90)]


class FakeSignalEngineWithSignal:
    def __init__(self, settings=None):
        self.settings = settings
        from types import SimpleNamespace

        self.analyst = SimpleNamespace(analyze=lambda candidate: SimpleNamespace())
        self.risk_manager = SimpleNamespace(
            evaluate=lambda *args, **kwargs: SimpleNamespace(allowed=True, reasons=["ok"], position_notional_usdt=200)
        )

    def generate_signals(self, *args, **kwargs):
        from app.data.schema import Direction, StructureType, TradeSignal

        return [
            TradeSignal(
                symbol="BTCUSDT",
                direction=Direction.LONG,
                confidence=0.8,
                rr=2.0,
                score=1.1,
                entry=100000,
                stop_loss=99000,
                take_profit=102000,
                structure=StructureType.PULLBACK,
                reasons=["test"],
            )
        ]


@pytest.mark.asyncio
async def test_run_scan_once_logs_trade_execution_failures(monkeypatch):
    journal_repo = NonBlockingJournalRepo(session=object())

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollectorWithCandidate())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngineWithSignal)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", FailingExecutionEngine)

    result = await run_scan_once(session=object(), settings=Settings())

    assert result["signals"] == 1
    assert result["simulated_trades"] == 0
    assert journal_repo.events[-1]["event_type"] == "trade_execution_failed"


@pytest.mark.asyncio
async def test_run_scan_once_persists_force_closed_trade_from_execution_failure(monkeypatch):
    journal_repo = NonBlockingJournalRepo(session=object())
    saved_trades = []

    class CapturingTradeRepo(FakeTradeRepo):
        def save_trade(self, trade):
            saved_trades.append(trade)
            return trade

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollectorWithCandidate())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", CapturingTradeRepo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngineWithSignal)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", ForceClosedExecutionEngine)

    result = await run_scan_once(session=object(), settings=Settings())

    assert result["signals"] == 1
    assert result["simulated_trades"] == 0
    assert len(saved_trades) == 1
    assert saved_trades[0].status == "closed"
    assert any(event["event_type"] == "trade_force_closed" for event in journal_repo.events)


@pytest.mark.asyncio
async def test_run_scan_once_logs_error_context_from_live_trading_failure(monkeypatch):
    journal_repo = NonBlockingJournalRepo(session=object())

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollectorWithCandidate())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngineWithSignal)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", ForceClosedExecutionEngineWithContext)

    await run_scan_once(session=object(), settings=Settings())

    execution_failed = next(event for event in journal_repo.events if event["event_type"] == "trade_execution_failed")
    assert execution_failed["details"]["error_context"]["symbol"] == "BTCUSDT"
    assert execution_failed["details"]["error_context"]["open_algo_orders"][0]["type"] == "STOP_MARKET"


@pytest.mark.asyncio
async def test_run_scan_once_uses_warning_for_handled_live_trading_failure(monkeypatch, caplog):
    journal_repo = NonBlockingJournalRepo(session=object())

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollectorWithCandidate())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", FakeTradeRepo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngineWithSignal)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", ForceClosedExecutionEngineWithContext)

    with caplog.at_level(logging.WARNING):
        await run_scan_once(session=object(), settings=Settings())

    assert "trade execution failed: protection failed" in caplog.text
