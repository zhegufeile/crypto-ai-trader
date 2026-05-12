from app.data.schema import Candidate
from app.knowledge.distiller import StrategyCard


class PromptBuilder:
    def build_candidate_prompt(self, candidate: Candidate, cards: list[StrategyCard]) -> str:
        matching_cards = [card for card in cards if card.matches(candidate.snapshot)]
        card_lines = [
            f"- {card.name}: entry={', '.join(card.entry_conditions) or 'none'}, "
            f"exit={', '.join(card.exit_conditions) or 'none'}, "
            f"bias={card.confidence_bias:.2f}, market={card.market}, timeframe={card.timeframe}, "
            f"tier={card.strategy_tier}, tier_score={card.tier_score:.1f}"
            for card in matching_cards
        ]
        card_block = "\n".join(card_lines) if card_lines else "- none"
        snapshot = candidate.snapshot
        return (
            f"Analyze {snapshot.symbol}.\n"
            f"Price={snapshot.price}, 24h_change={snapshot.price_change_pct_24h}, "
            f"quote_volume={snapshot.quote_volume_24h}, funding={snapshot.funding_rate}, "
            f"oi={snapshot.oi}, btc_trend={snapshot.btc_trend}.\n"
            f"Candidate hard_score={candidate.hard_score} tags={', '.join(candidate.tags) or 'none'}.\n"
            f"Relevant strategy cards:\n{card_block}"
        )
