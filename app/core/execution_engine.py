from app.config import Settings
from app.core.simulator import SimulatedTrade, Simulator
from app.data.schema import MarketSnapshot, RiskDecision, TradeSignal


class ExecutionEngine:
    def __init__(self, simulator: Simulator | None = None, settings: Settings | None = None) -> None:
        self.simulator = simulator or Simulator(settings=settings)

    def execute_simulated(
        self, signal: TradeSignal, risk_decision: RiskDecision
    ) -> SimulatedTrade | None:
        if not risk_decision.allowed:
            return None
        return self.simulator.open_trade(signal, risk_decision.position_notional_usdt)

    def manage_simulated(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> SimulatedTrade:
        return self.simulator.update_trade(trade, snapshot)
