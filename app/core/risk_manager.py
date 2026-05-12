from datetime import UTC, datetime, timedelta

from app.config import Settings, get_settings
from app.core.simulator import SimulatedTrade
from app.data.schema import AnalysisResult, Candidate, Direction, RiskDecision


class RiskManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def evaluate(
        self,
        candidate: Candidate,
        analysis: AnalysisResult,
        open_positions: int = 0,
        realized_pnl_today: float = 0,
        active_trades: list[SimulatedTrade] | None = None,
        recent_closed_trades: list[SimulatedTrade] | None = None,
    ) -> RiskDecision:
        reasons: list[str] = []
        symbol = candidate.snapshot.symbol
        active_trades = active_trades or []
        recent_closed_trades = recent_closed_trades or []
        if symbol in self.settings.blacklisted_symbols:
            reasons.append("symbol is blacklisted")
        if analysis.direction == Direction.NEUTRAL:
            reasons.append("analysis direction is neutral")
        if analysis.confidence < self.settings.confidence_threshold:
            reasons.append("confidence is below threshold")
        if analysis.rr < self.settings.min_rr:
            reasons.append("risk/reward is below threshold")
        if open_positions >= self.settings.max_open_positions:
            reasons.append("maximum open positions reached")
        if any(trade.symbol == symbol for trade in active_trades):
            reasons.append("symbol already has an active or pending position")
        if self._count_active_direction(active_trades, analysis.direction.value) >= self.settings.max_same_direction_positions:
            reasons.append("same-direction exposure limit is reached")
        if self._count_active_structure(active_trades, analysis.structure.value) >= self.settings.max_same_structure_positions:
            reasons.append("same-structure exposure limit is reached")
        if self._symbol_cooldown_active(symbol, recent_closed_trades):
            reasons.append("symbol is cooling down after a recent trade")
        if self._consecutive_losses(recent_closed_trades) >= self.settings.max_consecutive_losses:
            reasons.append("consecutive loss cooldown is active")
        if realized_pnl_today <= -abs(self.settings.daily_max_loss_usdt):
            reasons.append("daily loss circuit breaker is active")
        if candidate.snapshot.quote_volume_24h < self.settings.min_volume_usdt:
            reasons.append("liquidity is below minimum threshold")
        if candidate.snapshot.funding_rate is not None and abs(candidate.snapshot.funding_rate) > 0.003:
            reasons.append("funding rate is overheated")
        if candidate.snapshot.market_regime == "range_or_chop":
            reasons.append("market regime is range or chop")
        if candidate.snapshot.reversal_stage == "late_reversal":
            reasons.append("setup is too late in the reversal sequence")
        if (
            analysis.structure.value in {"breakout", "momentum"}
            and candidate.snapshot.follow_through_score < self.settings.min_follow_through_score
        ):
            reasons.append("follow-through is too weak for an expansion setup")
        if candidate.snapshot.relative_strength_score < 0.35:
            reasons.append("relative strength is too weak")
        if candidate.snapshot.onchain_honeypot:
            reasons.append("onchain security flags this token as honeypot")
        if candidate.snapshot.onchain_is_safe_buy is False:
            reasons.append("onchain security does not consider this token safe to buy")
        if str(candidate.snapshot.onchain_risk_level).upper() == "CRITICAL":
            reasons.append("onchain risk level is critical")
        if candidate.snapshot.onchain_liquidity_usd is not None and candidate.snapshot.onchain_liquidity_usd < 10_000:
            reasons.append("onchain liquidity is too low")

        return RiskDecision(
            allowed=not reasons,
            reasons=reasons or ["risk checks passed"],
            position_notional_usdt=self.settings.max_position_notional_usdt if not reasons else 0,
        )

    @staticmethod
    def _count_active_direction(active_trades: list[SimulatedTrade], direction: str) -> int:
        return len([trade for trade in active_trades if trade.direction == direction and trade.is_active])

    @staticmethod
    def _count_active_structure(active_trades: list[SimulatedTrade], structure: str) -> int:
        return len([trade for trade in active_trades if trade.structure == structure and trade.is_active])

    def _symbol_cooldown_active(self, symbol: str, recent_closed_trades: list[SimulatedTrade]) -> bool:
        cutoff = datetime.now(UTC) - timedelta(minutes=self.settings.symbol_cooldown_minutes)
        for trade in recent_closed_trades:
            closed_at = trade.closed_at or trade.updated_at
            if trade.symbol == symbol and closed_at is not None and closed_at >= cutoff:
                return True
        return False

    @staticmethod
    def _consecutive_losses(recent_closed_trades: list[SimulatedTrade]) -> int:
        ordered = sorted(
            recent_closed_trades,
            key=lambda trade: trade.closed_at or trade.updated_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        streak = 0
        for trade in ordered:
            if trade.realized_pnl_usdt < 0:
                streak += 1
                continue
            if trade.realized_pnl_usdt > 0:
                break
        return streak
