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
        if not self.settings.use_simulation:
            return self.live_trader.open_trade(signal, risk_decision.position_notional_usdt)
        return self.simulator.open_trade(signal, risk_decision.position_notional_usdt)

    def manage_simulated(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> SimulatedTrade:
        if not self.settings.use_simulation:
            return self.live_trader.update_trade(trade, snapshot)
        return self.simulator.update_trade(trade, snapshot)
