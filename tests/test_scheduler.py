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

    def claim_pending_entry(self, trade_id):
        return None


class OpenTradeRepo(FakeTradeRepo):
    def __init__(self, session, trade):
        super().__init__(session)
        self.trades = [trade]
        self.updated_trades = []

    def list_open_trades(self):
        return list(self.trades)

    def claim_pending_entry(self, trade_id):
        for index, trade in enumerate(self.trades):
            if trade.id == trade_id and trade.status == "pending_entry":
                claimed = trade.model_copy(update={"status": "entry_in_progress"})
                self.trades[index] = claimed
                return claimed
        return None

    def update_trade(self, trade):
        self.updated_trades.append(trade)
        self.trades = [trade if item.id == trade.id else item for item in self.trades]
        return trade


class LostClaimTradeRepo(OpenTradeRepo):
    def claim_pending_entry(self, trade_id):
        return None


class FakeJournalRepo:
    def __init__(self, session):
        self.session = session
        self.events = []

    def count_recent_actions(self, window_minutes: int, event_types=None):
        return 99

    def log_event(self, **kwargs):
        self.events.append(kwargs)
        return kwargs

    def has_trade_event(self, trade_id: str | None, event_type: str) -> bool:
        return any(event.get("trade_id") == trade_id and event.get("event_type") == event_type for event in self.events)


class NonBlockingJournalRepo(FakeJournalRepo):
    def count_recent_actions(self, window_minutes: int, event_types=None):
        return 0

    def has_recent_symbol_event(self, symbol: str, window_minutes: int, event_types=None):
        return False


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


class ClosingManagementEngine:
    def __init__(self, settings=None):
        self.settings = settings
        self.snapshots = []

    def manage_simulated(self, trade, snapshot):
        self.snapshots.append(snapshot)
        trade.status = "closed"
        trade.closed_at = snapshot.timestamp
        trade.exit_reason = "exchange position already flat"
        trade.remaining_notional_usdt = 0
        trade.remaining_quantity = 0
        trade.remaining_size_pct = 0
        trade.unrealized_pnl_usdt = 0
        trade.pnl_usdt = trade.realized_pnl_usdt
        return trade

    def execute_simulated(self, signal, risk_decision):
        return None


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


class FakeSignalEngineWithDuplicateSignals(FakeSignalEngineWithSignal):
    def generate_signals(self, *args, **kwargs):
        signals = super().generate_signals(*args, **kwargs)
        return signals + [signals[0].model_copy()]


class RecentFailureJournalRepo(NonBlockingJournalRepo):
    def has_recent_symbol_event(self, symbol: str, window_minutes: int, event_types=None):
        return symbol == "BTCUSDT" and event_types == [
            "trade_force_closed",
            "trade_execution_failed",
            "trade_manage_failed",
        ]


class OpeningExecutionEngine:
    def __init__(self, settings=None):
        self.settings = settings
        self.executed_symbols = []

    def manage_simulated(self, trade, snapshot):
        return trade

    def execute_simulated(self, signal, risk_decision):
        self.executed_symbols.append(signal.symbol)
        return SimulatedTrade(
            symbol=signal.symbol,
            direction=signal.direction.value,
            structure=signal.structure.value,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            notional_usdt=risk_decision.position_notional_usdt,
            remaining_notional_usdt=risk_decision.position_notional_usdt,
            initial_stop_loss=signal.stop_loss,
            current_stop_loss=signal.stop_loss,
            tp1_price=signal.entry * 1.01,
            tp2_price=signal.entry * 1.02,
            status="open",
            quantity=1,
            remaining_quantity=1,
            entry_mode="market",
            entry_confirmed=True,
            confirmation_required=False,
        )


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
async def test_run_scan_once_manages_open_trade_even_when_symbol_is_not_in_candidates(monkeypatch):
    from app.core.simulator import SimulatedTrade

    open_trade = SimulatedTrade(
        symbol="LABUSDT",
        direction="short",
        structure="momentum",
        entry=4.0033,
        stop_loss=4.0611,
        take_profit=3.8451,
        notional_usdt=50.0,
        quantity=12.0,
        remaining_notional_usdt=50.0,
        remaining_quantity=12.0,
        initial_stop_loss=4.0611,
        current_stop_loss=4.0611,
        tp1_price=3.95,
        tp2_price=3.90,
        status="open",
    )
    journal_repo = NonBlockingJournalRepo(session=object())
    trade_repo = OpenTradeRepo(session=object(), trade=open_trade)
    engine = ClosingManagementEngine()

    class PassiveSignalEngine:
        def __init__(self, settings=None):
            self.settings = settings

        def generate_signals(self, *args, **kwargs):
            return []

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollector())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", lambda session: trade_repo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", PassiveSignalEngine)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", lambda settings=None: engine)

    result = await run_scan_once(session=object(), settings=Settings())

    assert result["managed_positions"] == 1
    assert engine.snapshots
    assert engine.snapshots[0].symbol == "LABUSDT"
    assert trade_repo.trades[0].status == "closed"
    assert trade_repo.trades[0].exit_reason == "exchange position already flat"


@pytest.mark.asyncio
async def test_run_scan_once_skips_pending_trade_when_entry_claim_is_lost(monkeypatch):
    pending_trade = SimulatedTrade(
        symbol="LABUSDT",
        direction="short",
        structure="momentum",
        entry=4.0033,
        stop_loss=4.0611,
        take_profit=3.8451,
        notional_usdt=50.0,
        quantity=12.0,
        remaining_notional_usdt=50.0,
        remaining_quantity=12.0,
        initial_stop_loss=4.0611,
        current_stop_loss=4.0611,
        tp1_price=3.95,
        tp2_price=3.90,
        status="pending_entry",
        entry_confirmed=False,
        confirmation_required=True,
    )
    journal_repo = NonBlockingJournalRepo(session=object())
    trade_repo = LostClaimTradeRepo(session=object(), trade=pending_trade)
    engine = ClosingManagementEngine()

    class PassiveSignalEngine:
        def __init__(self, settings=None):
            self.settings = settings

        def generate_signals(self, *args, **kwargs):
            return []

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollector())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", lambda session: trade_repo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", PassiveSignalEngine)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", lambda settings=None: engine)

    result = await run_scan_once(session=object(), settings=Settings())

    assert result["managed_positions"] == 0
    assert engine.snapshots == []
    assert trade_repo.trades[0].status == "pending_entry"


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


@pytest.mark.asyncio
async def test_run_scan_once_blocks_duplicate_symbol_within_same_execution_set(monkeypatch):
    journal_repo = NonBlockingJournalRepo(session=object())
    execution_engine = OpeningExecutionEngine()
    trade_repo = FakeTradeRepo(session=object())

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollectorWithCandidate())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", lambda session: trade_repo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngineWithDuplicateSignals)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", lambda settings=None: execution_engine)

    result = await run_scan_once(session=object(), settings=Settings())

    assert result["signals"] == 2
    assert result["simulated_trades"] == 1
    assert execution_engine.executed_symbols == ["BTCUSDT"]
    blocked = [event for event in journal_repo.events if event["event_type"] == "trade_blocked"]
    assert blocked
    assert blocked[-1]["details"]["reasons"] == ["symbol already has an active or pending position"]


@pytest.mark.asyncio
async def test_run_scan_once_blocks_recent_symbol_reentry(monkeypatch):
    journal_repo = RecentFailureJournalRepo(session=object())
    execution_engine = OpeningExecutionEngine()
    trade_repo = FakeTradeRepo(session=object())

    monkeypatch.setattr("app.core.scheduler.MarketCollector", lambda settings=None: FakeCollectorWithCandidate())
    monkeypatch.setattr("app.core.scheduler.SignalRepository", FakeSignalRepo)
    monkeypatch.setattr("app.core.scheduler.TradeRepository", lambda session: trade_repo)
    monkeypatch.setattr("app.core.scheduler.TradeJournalRepository", lambda session: journal_repo)
    monkeypatch.setattr("app.core.scheduler.TradeFeeRepository", FakeFeeRepo)
    monkeypatch.setattr("app.core.scheduler.SignalEngine", FakeSignalEngineWithSignal)
    monkeypatch.setattr("app.core.scheduler.ExecutionEngine", lambda settings=None: execution_engine)

    result = await run_scan_once(session=object(), settings=Settings())

    assert result["signals"] == 1
    assert result["simulated_trades"] == 0
    assert execution_engine.executed_symbols == []
    blocked = [event for event in journal_repo.events if event["event_type"] == "trade_blocked"]
    assert blocked
    assert blocked[-1]["message"] == "recent symbol activity blocked immediate re-entry"


def test_log_trade_transition_events_dedupes_trade_confirmed():
    from app.core.scheduler import _log_trade_transition_events

    journal_repo = NonBlockingJournalRepo(session=object())
    before = SimulatedTrade(
        id="trade-1",
        symbol="BTCUSDT",
        direction="long",
        structure="breakout",
        entry=100,
        stop_loss=95,
        take_profit=110,
        notional_usdt=100,
        remaining_notional_usdt=100,
        initial_stop_loss=95,
        current_stop_loss=95,
        tp1_price=105,
        tp2_price=110,
        status="pending_entry",
        entry_confirmed=False,
        confirmation_required=True,
    )
    after = before.model_copy(update={"status": "open", "entry_confirmed": True})

    first = _log_trade_transition_events(journal_repo, before, after)
    second = _log_trade_transition_events(journal_repo, before, after)

    assert first == ["trade_confirmed"]
    assert second == []
