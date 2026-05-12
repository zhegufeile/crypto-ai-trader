import json
from pathlib import Path

from app.knowledge.distiller import StrategyCard


class StrategyStore:
    def __init__(self, root: Path | str = "obsidian/strategy_cards") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, card: StrategyCard) -> Path:
        path = self.root / f"{card.name}.json"
        path.write_text(card.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_markdown(self, card: StrategyCard) -> Path:
        path = self.root / f"{card.name}.md"
        path.write_text(self._to_markdown(card), encoding="utf-8")
        return path

    def load(self, name: str) -> StrategyCard | None:
        json_path = self.root / f"{name}.json"
        if json_path.exists():
            return StrategyCard(**json.loads(json_path.read_text(encoding="utf-8")))
        md_path = self.root / f"{name}.md"
        if md_path.exists():
            return self._from_markdown(md_path)
        return None

    def list_cards(self) -> list[StrategyCard]:
        cards_by_name: dict[str, StrategyCard] = {}
        for path in sorted(self.root.glob("*.json")):
            card = StrategyCard(**json.loads(path.read_text(encoding="utf-8")))
            cards_by_name[card.name] = card
        for path in sorted(self.root.glob("*.md")):
            card = self._from_markdown(path)
            if card is not None:
                cards_by_name[card.name] = card
        return list(cards_by_name.values())

    def _to_markdown(self, card: StrategyCard) -> str:
        lines = [
            f"# {card.name}",
            "",
            f"- description: {card.description}",
            f"- market: {card.market}",
            f"- timeframe: {card.timeframe}",
            f"- creator: {card.creator}",
            f"- confidence_bias: {card.confidence_bias}",
            f"- preferred_symbols: {', '.join(card.preferred_symbols) or 'none'}",
            f"- avoided_symbols: {', '.join(card.avoided_symbols) or 'none'}",
            f"- preferred_market_states: {', '.join(card.preferred_market_states) or 'none'}",
            f"- entry_conditions: {', '.join(card.entry_conditions) or 'none'}",
            f"- exit_conditions: {', '.join(card.exit_conditions) or 'none'}",
            f"- invalidation_conditions: {', '.join(card.invalidation_conditions) or 'none'}",
            f"- risk_notes: {', '.join(card.risk_notes) or 'none'}",
            f"- historical_win_rate: {card.historical_win_rate if card.historical_win_rate is not None else 'unknown'}",
            f"- historical_rr: {card.historical_rr if card.historical_rr is not None else 'unknown'}",
            f"- sample_size: {card.sample_size}",
            f"- strategy_tier: {card.strategy_tier}",
            f"- tier_score: {card.tier_score}",
            f"- tier_rationale: {' | '.join(card.tier_rationale) or 'none'}",
            f"- tags: {', '.join(card.tags) or 'none'}",
            f"- source_posts: {card.source_posts}",
        ]
        return "\n".join(lines) + "\n"

    def _from_markdown(self, path: Path) -> StrategyCard | None:
        fields: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("- ") or ":" not in line:
                continue
            key, value = line[2:].split(":", 1)
            fields[key.strip()] = value.strip()
        if not fields:
            return None
        return StrategyCard(
            name=path.stem,
            description=fields.get("description", ""),
            market=fields.get("market", "any"),
            timeframe=fields.get("timeframe", "any"),
            creator=fields.get("creator", "unknown"),
            confidence_bias=float(fields.get("confidence_bias", "0") or 0),
            preferred_symbols=self._split_list(fields.get("preferred_symbols")),
            avoided_symbols=self._split_list(fields.get("avoided_symbols")),
            preferred_market_states=self._split_list(fields.get("preferred_market_states")),
            entry_conditions=self._split_list(fields.get("entry_conditions")),
            exit_conditions=self._split_list(fields.get("exit_conditions")),
            invalidation_conditions=self._split_list(fields.get("invalidation_conditions")),
            risk_notes=self._split_list(fields.get("risk_notes")),
            historical_win_rate=self._optional_float(fields.get("historical_win_rate")),
            historical_rr=self._optional_float(fields.get("historical_rr")),
            sample_size=int(fields.get("sample_size", "0") or 0),
            strategy_tier=fields.get("strategy_tier", "watchlist"),
            tier_score=float(fields.get("tier_score", "0") or 0),
            tier_rationale=self._split_pipe_list(fields.get("tier_rationale")),
            tags=self._split_list(fields.get("tags")),
            source_posts=int(fields.get("source_posts", "0") or 0),
        )

    @staticmethod
    def _split_list(value: str | None) -> list[str]:
        if not value or value == "none":
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    @staticmethod
    def _split_pipe_list(value: str | None) -> list[str]:
        if not value or value == "none":
            return []
        return [item.strip() for item in value.split("|") if item.strip()]

    @staticmethod
    def _optional_float(value: str | None) -> float | None:
        if not value or value == "unknown":
            return None
        return float(value)
