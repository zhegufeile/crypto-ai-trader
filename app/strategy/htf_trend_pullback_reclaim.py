from app.data.schema import Candidate
from app.strategy.base import Strategy


class HtfTrendPullbackReclaimStrategy(Strategy):
    name = "htf_trend_pullback_reclaim"

    def score(self, candidate: Candidate) -> tuple[float, list[str]]:
        snapshot = candidate.snapshot
        score = 0.0
        reasons: list[str] = []

        if snapshot.market_regime != "uptrend_pullback":
            return score, reasons
        if snapshot.htf_trend_bias is not None and snapshot.htf_trend_bias >= 0.25:
            score += 10
            reasons.append("higher timeframe trend is aligned with the pullback reclaim")
        if snapshot.retest_quality_score >= 0.65:
            score += 8
            reasons.append("pullback retest quality is strong enough for reclaim entries")
        if snapshot.relative_strength_score >= 0.65:
            score += 6
            reasons.append("relative strength still identifies the symbol as a leader")
        if snapshot.distance_from_vwap_atr is not None and snapshot.distance_from_vwap_atr <= 0.75:
            score += 4
            reasons.append("price remains close enough to value instead of chasing extension")
        return score, reasons
