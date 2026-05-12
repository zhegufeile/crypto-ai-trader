from app.data.schema import AnalysisResult, Candidate


class SignalScorer:
    def score(self, candidate: Candidate, analysis: AnalysisResult) -> float:
        rr_score = min(analysis.rr / 3, 1) * 25
        confidence_score = analysis.confidence * 45
        hard_score = candidate.hard_score * 0.30
        return round(min(hard_score + confidence_score + rr_score, 100), 2)
