from app.data.schema import Candidate
from app.strategy.base import Strategy


class SentimentStrategy(Strategy):
    name = "sentiment"

    def score(self, candidate: Candidate) -> tuple[float, list[str]]:
        if "kol_attention" in candidate.tags or "alpha" in candidate.tags:
            return 20, ["external attention tag is present"]
        return 0, []
