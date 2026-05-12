from app.data.schema import AnalysisResult, Direction


def normalize_analysis(result: AnalysisResult) -> AnalysisResult:
    result.confidence = max(0, min(result.confidence, 1))
    result.rr = max(0, result.rr)
    if result.direction not in {Direction.LONG, Direction.SHORT, Direction.NEUTRAL}:
        result.direction = Direction.NEUTRAL
    return result
