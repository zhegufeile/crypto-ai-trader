from app.data.schema import Candidate
from app.strategy.base import Strategy


class BreakoutRetestConfirmationStrategy(Strategy):
    name = "breakout_retest_confirmation"

    def score(self, candidate: Candidate) -> tuple[float, list[str]]:
        snapshot = candidate.snapshot
        score = 0.0
        reasons: list[str] = []

        if snapshot.market_regime != "trend_or_acceleration":
            return score, reasons
        if snapshot.breakout_acceptance_score is not None and snapshot.breakout_acceptance_score >= 0.65:
            score += 10
            reasons.append("breakout acceptance remains above the trigger zone")
        if snapshot.relative_volume_ratio is not None and snapshot.relative_volume_ratio >= 1.35:
            score += 8
            reasons.append("relative volume confirms the breakout attempt")
        if snapshot.distance_from_breakout_level_atr is not None and snapshot.distance_from_breakout_level_atr <= 0.35:
            score += 8
            reasons.append("entry is near the breakout retest instead of late extension")
        if snapshot.follow_through_score >= 0.6:
            score += 4
            reasons.append("follow-through still supports continuation after retest")
        return score, reasons
