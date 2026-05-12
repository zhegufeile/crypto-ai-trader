from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib

from app.knowledge.distiller import KolStrategyDistiller, StrategyCard
from app.knowledge.kol_import import RawKOLPost, extract_symbols_from_text, normalize_symbol


@dataclass
class PipelineResult:
    kept_posts: list[RawKOLPost]
    rejected_posts: list[RawKOLPost]
    clusters: dict[str, list[RawKOLPost]]
    cards: list[StrategyCard]


class KOLPipeline:
    def deduplicate(self, posts: list[RawKOLPost]) -> list[RawKOLPost]:
        seen: set[str] = set()
        unique_posts: list[RawKOLPost] = []
        for post in posts:
            fingerprint = self._fingerprint(post)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique_posts.append(post)
        return unique_posts

    def filter_trade_relevant(self, posts: list[RawKOLPost]) -> tuple[list[RawKOLPost], list[RawKOLPost]]:
        kept: list[RawKOLPost] = []
        rejected: list[RawKOLPost] = []
        for post in posts:
            if self._is_trade_relevant(post):
                kept.append(post)
            else:
                rejected.append(post)
        return kept, rejected

    def cluster_by_kol_and_symbol(self, posts: list[RawKOLPost]) -> dict[str, list[RawKOLPost]]:
        clusters: dict[str, list[RawKOLPost]] = defaultdict(list)
        for post in posts:
            key = self._cluster_key(post)
            clusters[key].append(post)
        return dict(sorted(clusters.items(), key=lambda item: len(item[1]), reverse=True))

    def build_strategy_cards(self, clusters: dict[str, list[RawKOLPost]]) -> list[StrategyCard]:
        distiller = KolStrategyDistiller()
        cards: list[StrategyCard] = []
        for key, posts in clusters.items():
            if not posts:
                continue
            author = posts[0].author or "unknown"
            symbol_part = self._primary_symbol(posts) or "generic"
            name = f"{self._slug(author)}_{self._slug(symbol_part)}"
            text_blobs = [self._compress_post(post) for post in posts]
            card = distiller.distill(name, text_blobs, creator=author)
            card.source_posts = len(posts)
            card.sample_size = len(posts)
            cards.append(card)
        return cards

    def run(self, posts: list[RawKOLPost]) -> PipelineResult:
        unique_posts = self.deduplicate(posts)
        kept_posts, rejected_posts = self.filter_trade_relevant(unique_posts)
        clusters = self.cluster_by_kol_and_symbol(kept_posts)
        cards = self.build_strategy_cards(clusters)
        return PipelineResult(
            kept_posts=kept_posts,
            rejected_posts=rejected_posts,
            clusters=clusters,
            cards=cards,
        )

    @staticmethod
    def _fingerprint(post: RawKOLPost) -> str:
        base = "|".join(
            [
                post.author.strip().lower(),
                post.text.strip().lower(),
                post.source.strip().lower(),
                post.url.strip().lower() if post.url else "",
            ]
        )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_trade_relevant(post: RawKOLPost) -> bool:
        text = post.text.lower()
        if len(text) < 20:
            return False
        trade_terms = [
            "entry",
            "exit",
            "breakout",
            "pullback",
            "support",
            "resistance",
            "liquidity",
            "funding",
            "oi",
            "open interest",
            "volume",
            "risk",
            "setup",
            "target",
            "stop",
            "long",
            "short",
            "做多",
            "做空",
            "突破",
            "回踩",
            "支撑",
            "阻力",
            "放量",
            "持仓",
            "资金费率",
            "止损",
            "止盈",
            "入场",
            "出场",
        ]
        if any(term in text for term in trade_terms):
            return True
        return bool(post.symbols)

    @staticmethod
    def _cluster_key(post: RawKOLPost) -> str:
        symbol = KOLPipeline._primary_symbol([post]) or "generic"
        return f"{post.author.lower()}::{symbol}"

    @staticmethod
    def _primary_symbol(posts: list[RawKOLPost]) -> str | None:
        for post in posts:
            if post.symbols:
                return normalize_symbol(post.symbols[0])
            extracted = extract_symbols_from_text(post.text)
            if extracted:
                return normalize_symbol(extracted[0])
        return None

    @staticmethod
    def _compress_post(post: RawKOLPost) -> str:
        parts = [post.text.strip()]
        if post.symbols:
            parts.append(f"symbols={','.join(post.symbols)}")
        if post.tags:
            parts.append(f"tags={','.join(post.tags)}")
        return " | ".join(parts)

    @staticmethod
    def _slug(value: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
        return cleaned or "unknown"
