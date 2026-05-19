from app.config import Settings, get_settings
from app.core.live_trader import BinanceLiveTrader
from app.core.simulator import SimulatedTrade, Simulator
from app.data.schema import MarketSnapshot, RiskDecision, TradeSignal


class ExecutionEngine:
    def __init__(self, simulator: Simulator | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.simulator = simulator or Simulator(settings=self.settings)
        self.live_trader = BinanceLiveTrader(settings=self.settings)

    def execute_simulated(
        self, signal: TradeSignal, risk_decision: RiskDecision
    ) -> SimulatedTrade | None:
        if not risk_decision.allowed:
            return None
        trade = self.prepare_trade(signal, risk_decision)
        if trade is None:
            return None
        return self.execute_prepared_trade(trade)

    def prepare_trade(self, signal: TradeSignal, risk_decision: RiskDecision) -> SimulatedTrade | None:
        if not risk_decision.allowed:
            return None
        if not self.settings.use_simulation:
            return self.live_trader.prepare_trade(signal, risk_decision.position_notional_usdt)
        return self.simulator.open_trade(signal, risk_decision.position_notional_usdt)

    def execute_prepared_trade(self, trade: SimulatedTrade) -> SimulatedTrade:
        if not self.settings.use_simulation:
            return self.live_trader.enter_prepared_trade(trade)
        return trade

    def manage_simulated(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> SimulatedTrade:
        if not self.settings.use_simulation:
            return self.live_trader.update_trade(trade, snapshot)
        return self.simulator.update_trade(trade, snapshot)
