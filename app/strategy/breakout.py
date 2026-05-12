from app.data.schema import Candidate
from app.strategy.base import Strategy


class BreakoutStrategy(Strategy):
    name = "breakout"

    def score(self, candidate: Candidate) -> tuple[float, list[str]]:
        snapshot = candidate.snapshot
        score = 0.0
        reasons: list[str] = []
        if snapshot.price_change_pct_24h > 4:
            score += 20
            reasons.append("positive 24h breakout pressure")
        if snapshot.quote_volume_24h > 100_000_000:
            score += 15
            reasons.append("volume supports breakout")
        if snapshot.oi and snapshot.oi > 0:
            score += 10
            reasons.append("open interest confirms participation")
        return score, reasons
