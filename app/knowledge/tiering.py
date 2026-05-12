from dataclasses import dataclass


@dataclass
class StrategyTierDecision:
    tier: str
    score: float
    rationale: list[str]


def compute_strategy_tier(
    *,
    sample_size: int,
    win_rate: float,
    avg_rr: float,
    tp1_hit_rate: float,
    tp2_hit_rate: float,
    breakeven_exit_rate: float,
    max_drawdown_rr: float,
) -> StrategyTierDecision:
    drawdown_penalty = abs(min(max_drawdown_rr, 0))
    score = round(
        win_rate * 100
        + avg_rr * 12
        + tp1_hit_rate * 8
        + tp2_hit_rate * 18
        + min(sample_size, 50) * 0.8
        - drawdown_penalty * 5
        - breakeven_exit_rate * 6,
        3,
    )

    rationale: list[str] = []
    if win_rate >= 0.6:
        rationale.append("win rate is holding above the core threshold")
    if avg_rr >= 2.0:
        rationale.append("average RR is strong enough for systematic execution")
    if tp2_hit_rate >= 0.35:
        rationale.append("second target is reached often enough to justify runners")
    if sample_size >= 8:
        rationale.append("sample size is large enough to trust more than anecdotes")
    if max_drawdown_rr >= -1.5:
        rationale.append("drawdown profile is still manageable")
    if breakeven_exit_rate >= 0.35:
        rationale.append("high breakeven exit rate suggests this still belongs in a lighter bucket")

    if sample_size >= 8 and win_rate >= 0.6 and score >= 85:
        tier = "core"
    elif sample_size >= 5 and score >= 65:
        tier = "candidate"
    else:
        tier = "watchlist"

    if not rationale:
        rationale.append("needs more data before promotion to the core bucket")

    return StrategyTierDecision(tier=tier, score=score, rationale=rationale[:4])
