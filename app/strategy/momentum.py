from app.data.schema import Candidate
from app.strategy.base import Strategy


class MomentumStrategy(Strategy):
    name = "momentum"

    def score(self, candidate: Candidate) -> tuple[float, list[str]]:
        snapshot = candidate.snapshot
        score = 0.0
        reasons: list[str] = []
        if abs(snapshot.price_change_pct_24h) >= 6:
            score += 20
            reasons.append("large move creates momentum setup")
        if snapshot.taker_buy_sell_ratio and snapshot.taker_buy_sell_ratio > 1.05:
            score += 10
            reasons.append("taker buy pressure is stronger than sell pressure")
        return score, reasons
