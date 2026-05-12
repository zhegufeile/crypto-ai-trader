from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.data.schema import MarketSnapshot


class StrategyCard(BaseModel):
    name: str
    description: str = ""
    market: str = "any"
    timeframe: str = "any"
    creator: str = "unknown"
    confidence_bias: float = 0.0
    preferred_symbols: list[str] = Field(default_factory=list)
    avoided_symbols: list[str] = Field(default_factory=list)
    preferred_market_states: list[str] = Field(default_factory=list)
    entry_conditions: list[str] = Field(default_factory=list)
    exit_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    historical_win_rate: float | None = None
    historical_rr: float | None = None
    sample_size: int = 0
    tags: list[str] = Field(default_factory=list)
    source_posts: int = 0
    strategy_tier: str = "watchlist"
    tier_score: float = 0.0
    tier_rationale: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def matches(self, snapshot: MarketSnapshot) -> bool:
        if snapshot.symbol in self.avoided_symbols:
            return False
        if self.preferred_symbols and snapshot.symbol not in self.preferred_symbols:
            return False
        if self.market == "bullish" and snapshot.price_change_pct_24h < 0:
            return False
        if self.market == "bearish" and snapshot.price_change_pct_24h > 0:
            return False
        return True

    def matches_post(self, post) -> bool:
        post_symbols = getattr(post, "symbols", []) or []
        if self.preferred_symbols and post_symbols and not any(symbol in self.preferred_symbols for symbol in post_symbols):
            return False
        if any(symbol in self.avoided_symbols for symbol in post_symbols):
            return False
        text = (getattr(post, "text", "") or "").lower()
        if self.market == "bullish" and any(term in text for term in ["short", "看空", "做空"]):
            return False
        if self.market == "bearish" and any(term in text for term in ["long", "看多", "做多"]):
            return False
        return True


class KolStrategyDistiller:
    def distill(self, name: str, posts: list[str], creator: str = "manual_import") -> StrategyCard:
        normalized_posts = [post.strip() for post in posts if post and post.strip()]
        joined = "\n".join(normalized_posts).lower()

        entry_conditions: list[str] = []
        exit_conditions: list[str] = ["stop_loss_hit", "target_reached"]
        invalidation_conditions: list[str] = [
            "btc_turns_against_setup",
            "liquidity_deteriorates",
            "funding_overheats",
        ]
        risk_notes: list[str] = [
            "kol posts are sentiment factors, not direct trade orders",
            "verify liquidity, funding and BTC backdrop before entry",
        ]
        preferred_market_states: list[str] = []
        tags: list[str] = []

        if self._contains(joined, ["breakout", "突破", "上破", "向上破位"]):
            entry_conditions.append("breakout")
            preferred_market_states.append("trend_or_acceleration")
            tags.append("breakout")
        if self._contains(joined, ["volume", "放量", "量能", "成交量"]):
            entry_conditions.append("volume_expansion")
            tags.append("volume")
        if self._contains(joined, ["oi", "持仓", "open interest"]):
            entry_conditions.append("oi_rising")
            tags.append("oi")
        if self._contains(joined, ["pullback", "回踩", "回调", "支撑"]):
            entry_conditions.append("pullback_confirmation")
            preferred_market_states.append("uptrend_pullback")
            tags.append("pullback")
            exit_conditions.append("support_lost")
        if self._contains(joined, ["sentiment", "情绪", "叙事", "热度"]):
            entry_conditions.append("sentiment_tailwind")
            tags.append("sentiment")

        preferred_symbols = self._extract_symbols(normalized_posts)
        market = self._infer_market(joined)
        timeframe = self._infer_timeframe(joined)
        confidence_bias = self._confidence_bias(entry_conditions, preferred_symbols)

        return StrategyCard(
            name=name,
            description=self._build_description(name, entry_conditions, preferred_market_states),
            market=market,
            timeframe=timeframe,
            creator=creator,
            confidence_bias=confidence_bias,
            preferred_symbols=preferred_symbols,
            preferred_market_states=preferred_market_states,
            entry_conditions=entry_conditions or ["manual_review_required"],
            exit_conditions=exit_conditions,
            invalidation_conditions=invalidation_conditions,
            risk_notes=risk_notes,
            historical_win_rate=None,
            historical_rr=None,
            sample_size=len(normalized_posts),
            tags=sorted(set(tags)) or ["manual"],
            source_posts=len(normalized_posts),
        )

    @staticmethod
    def _contains(joined: str, keywords: list[str]) -> bool:
        return any(keyword.lower() in joined for keyword in keywords)

    @staticmethod
    def _confidence_bias(entry_conditions: list[str], preferred_symbols: list[str]) -> float:
        bias = 0.0
        if len(entry_conditions) >= 3:
            bias += 0.12
        elif len(entry_conditions) == 2:
            bias += 0.08
        elif len(entry_conditions) == 1:
            bias += 0.04
        if preferred_symbols:
            bias += 0.03
        return round(min(bias, 0.2), 3)

    @staticmethod
    def _build_description(name: str, entry_conditions: list[str], market_states: list[str]) -> str:
        entry = ", ".join(entry_conditions) or "manual_review_required"
        state = ", ".join(market_states) or "any_market"
        return f"Strategy card for {name}: entry={entry}; market_state={state}."

    @staticmethod
    def _infer_market(joined: str) -> str:
        bullish = sum(keyword in joined for keyword in ["bull", "看多", "long", "做多", "突破"])
        bearish = sum(keyword in joined for keyword in ["bear", "看空", "short", "做空", "跌破"])
        if bullish > bearish:
            return "bullish"
        if bearish > bullish:
            return "bearish"
        return "any"

    @staticmethod
    def _infer_timeframe(joined: str) -> str:
        if any(keyword in joined for keyword in ["scalp", "短线", "5m", "15m", "intraday"]):
            return "intraday"
        if any(keyword in joined for keyword in ["1h", "4h", "日线", "swing", "波段"]):
            return "swing"
        if any(keyword in joined for keyword in ["position", "中线", "long-term", "长线"]):
            return "position"
        return "any"

    @staticmethod
    def _extract_symbols(posts: list[str]) -> list[str]:
        symbols: set[str] = set()
        for post in posts:
            for token in post.replace(",", " ").replace(".", " ").split():
                cleaned = token.strip().upper()
                if cleaned.endswith("USDT") and 5 <= len(cleaned) <= 20:
                    symbols.add(cleaned)
                if cleaned.startswith("$") and len(cleaned) > 1:
                    symbols.add(cleaned[1:].upper())
        return sorted(symbols)
