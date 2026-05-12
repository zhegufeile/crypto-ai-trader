from abc import ABC, abstractmethod

from app.data.schema import Candidate


class Strategy(ABC):
    name: str

    @abstractmethod
    def score(self, candidate: Candidate) -> tuple[float, list[str]]:
        """Return strategy score contribution and reasons."""
