from app.data.schema import Candidate
from app.strategy.base import Strategy


class PullbackStrategy(Strategy):
    name = "pullback"

    def score(self, candidate: Candidate) -> tuple[float, list[str]]:
        snapshot = candidate.snapshot
        if 1.5 <= abs(snapshot.price_change_pct_24h) <= 4 and snapshot.btc_trend in {"up", "flat"}:
            return 15, ["controlled move may suit pullback confirmation"]
        return 0, []
