from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import Settings, get_settings
from app.core.simulator import SimulatedTrade, Simulator
from app.data.binance_client import BinanceClient
from app.data.schema import Direction, MarketSnapshot, StructureType, TradeSignal
from app.knowledge.distiller import StrategyCard
from app.knowledge.kol_import import RawKOLPost
from app.knowledge.strategy_store import StrategyStore
from app.knowledge.tiering import compute_strategy_tier
from app.storage.repositories import KOLPostRepository, StrategyMetricRepository
from sqlmodel import Session


@dataclass
class TradeReplayResult:
    rr: float
    is_win: bool
    hold_hours: float
    tp1_hit: bool
    tp2_hit: bool
    break_even_exit: bool


@dataclass
class BacktestOutcome:
    strategy_name: str
    sample_size: int
    wins: int
    losses: int
    win_rate: float
    avg_rr: float
    total_rr: float
    avg_hold_hours: float
    tp1_hit_rate: float
    tp2_hit_rate: float
    breakeven_exit_rate: float
    max_drawdown_rr: float


class StrategyBacktester:
    def __init__(
        self,
        client: BinanceClient | None = None,
        store: StrategyStore | None = None,
        simulator: Simulator | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or BinanceClient(
            futures_base_url=self.settings.binance_base_url,
            spot_base_url=self.settings.binance_spot_base_url,
            proxy_url=self.settings.binance_proxy_url,
            proxy_fallback_enabled=self.settings.binance_proxy_fallback_enabled,
        )
        self.store = store or StrategyStore()
        self.simulator = simulator or Simulator(settings=self.settings)

    async def backtest_strategy(self, card: StrategyCard, posts: list[RawKOLPost]) -> BacktestOutcome:
        usable_posts = [post for post in posts if card.matches_post(post)]
        trade_results: list[TradeReplayResult] = []

        for post in usable_posts:
            result = await self._evaluate_post(card, post)
            if result is None:
                continue
            trade_results.append(result)

        wins = sum(1 for item in trade_results if item.is_win)
        losses = sum(1 for item in trade_results if not item.is_win)
        sample_size = len(trade_results)
        total_rr = round(sum(item.rr for item in trade_results), 4)
        win_rate = round(wins / sample_size, 4) if sample_size else 0.0
        avg_rr = round(total_rr / sample_size, 4) if sample_size else 0.0
        avg_hold_hours = round(sum(item.hold_hours for item in trade_results) / sample_size, 4) if sample_size else 0.0
        tp1_hit_rate = round(sum(1 for item in trade_results if item.tp1_hit) / sample_size, 4) if sample_size else 0.0
        tp2_hit_rate = round(sum(1 for item in trade_results if item.tp2_hit) / sample_size, 4) if sample_size else 0.0
        breakeven_exit_rate = (
            round(sum(1 for item in trade_results if item.break_even_exit) / sample_size, 4) if sample_size else 0.0
        )
        max_drawdown_rr = self._max_drawdown_rr([item.rr for item in trade_results])

        return BacktestOutcome(
            strategy_name=card.name,
            sample_size=sample_size,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            avg_rr=avg_rr,
            total_rr=total_rr,
            avg_hold_hours=avg_hold_hours,
            tp1_hit_rate=tp1_hit_rate,
            tp2_hit_rate=tp2_hit_rate,
            breakeven_exit_rate=breakeven_exit_rate,
            max_drawdown_rr=max_drawdown_rr,
        )

    async def update_store_metrics(self, session: Session) -> list[BacktestOutcome]:
        store = self.store
        post_repo = KOLPostRepository(session)
        metric_repo = StrategyMetricRepository(session)
        outcomes: list[BacktestOutcome] = []

        for card in store.list_cards():
            posts = self._records_to_posts(post_repo.list_posts(card.name))
            outcome = await self.backtest_strategy(card, posts)
            metric_repo.upsert(
                strategy_name=card.name,
                sample_size=outcome.sample_size,
                win_rate=outcome.win_rate,
                avg_rr=outcome.avg_rr,
                total_rr=outcome.total_rr,
                wins=outcome.wins,
                losses=outcome.losses,
                avg_hold_hours=outcome.avg_hold_hours,
                tp1_hit_rate=outcome.tp1_hit_rate,
                tp2_hit_rate=outcome.tp2_hit_rate,
                breakeven_exit_rate=outcome.breakeven_exit_rate,
                max_drawdown_rr=outcome.max_drawdown_rr,
            )
            card.historical_win_rate = outcome.win_rate
            card.historical_rr = outcome.avg_rr
            card.sample_size = outcome.sample_size
            tier = compute_strategy_tier(
                sample_size=outcome.sample_size,
                win_rate=outcome.win_rate,
                avg_rr=outcome.avg_rr,
                tp1_hit_rate=outcome.tp1_hit_rate,
                tp2_hit_rate=outcome.tp2_hit_rate,
                breakeven_exit_rate=outcome.breakeven_exit_rate,
                max_drawdown_rr=outcome.max_drawdown_rr,
            )
            card.strategy_tier = tier.tier
            card.tier_score = tier.score
            card.tier_rationale = tier.rationale
            card.tags = _replace_tier_tags(card.tags, tier.tier)
            store.save(card)
            store.save_markdown(card)
            outcomes.append(outcome)
        return outcomes

    async def _evaluate_post(self, card: StrategyCard, post: RawKOLPost) -> TradeReplayResult | None:
        symbol = self._primary_symbol(card, post)
        if not symbol or post.created_at is None:
            return None
        klines = await self.client.get_klines(symbol, interval="1h", limit=72)
        if not klines:
            return None
        entry_index = self._find_entry_index(klines, post.created_at)
        if entry_index is None:
            return None

        entry_candle = klines[entry_index]
        signal = self._build_signal(card, symbol, entry_candle)
        if signal is None:
            return None

        trade = self.simulator.open_trade(signal, notional_usdt=100.0)
        forward = klines[entry_index + 1 : entry_index + 37]
        if not forward:
            return None

        last_snapshot: MarketSnapshot | None = None
        for candle in forward:
            snapshot = self._snapshot_from_candle(symbol, candle, signal.direction, trade.entry, trade.current_stop_loss)
            last_snapshot = snapshot
            trade = self.simulator.update_trade(trade, snapshot)
            if not trade.is_active:
                break

        if trade.is_active and last_snapshot is not None:
            exit_price = float(forward[-1][4])
            trade = self._force_close_trade(trade, exit_price)

        return self._result_from_trade(trade)

    def _build_signal(self, card: StrategyCard, symbol: str, candle: list) -> TradeSignal | None:
        direction = Direction.SHORT if self._infer_direction(card) == "short" else Direction.LONG
        structure = self._infer_structure(card)
        entry = float(candle[4])
        stop_pct = 0.02 if structure == StructureType.BREAKOUT else 0.018
        rr = 2.0 if structure == StructureType.PULLBACK else 2.4
        if direction == Direction.LONG:
            stop_loss = entry * (1 - stop_pct)
            take_profit = entry * (1 + stop_pct * rr)
        else:
            stop_loss = entry * (1 + stop_pct)
            take_profit = entry * (1 - stop_pct * rr)
        return TradeSignal(
            symbol=symbol,
            direction=direction,
            confidence=min(0.9, 0.65 + card.confidence_bias),
            rr=rr,
            score=70 + card.confidence_bias * 100,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            structure=structure,
            reasons=card.entry_conditions,
            management_plan=card.exit_conditions + card.invalidation_conditions,
            created_at=self._candle_open_datetime(candle),
        )

    def _snapshot_from_candle(
        self,
        symbol: str,
        candle: list,
        direction: Direction,
        entry: float,
        stop_loss: float,
    ) -> MarketSnapshot:
        open_price = float(candle[1])
        high = float(candle[2])
        low = float(candle[3])
        close = float(candle[4])
        range_size = max(high - low, 1e-9)
        body = close - open_price
        body_pct = body / open_price if open_price else 0
        if direction == Direction.SHORT:
            body_pct *= -1
            close_location = (high - close) / range_size
        else:
            close_location = (close - low) / range_size

        follow_through = max(0.0, min(1.0, 0.35 + max(body_pct, 0) * 20 + close_location * 0.35))
        stop_distance = abs(entry - stop_loss) or max(entry * 0.01, 1e-6)
        if direction == Direction.SHORT:
            retest_buffer = max(0.0, min(1.0, (high - entry) / stop_distance))
        else:
            retest_buffer = max(0.0, min(1.0, (entry - low) / stop_distance))
        retest_quality = max(0.0, min(1.0, 0.72 - retest_buffer * 0.35 + close_location * 0.18))
        regime = "trend_or_acceleration" if abs(body_pct) >= 0.0035 else "transition"

        return MarketSnapshot(
            symbol=symbol,
            timestamp=self._candle_close_datetime(candle),
            price=close,
            price_change_pct_24h=body_pct * 100,
            quote_volume_24h=float(candle[5]) if len(candle) > 5 else 0,
            btc_trend="up" if direction == Direction.LONG else "down",
            market_regime=regime,
            reversal_stage="trend",
            relative_strength_score=0.68 if abs(body_pct) > 0 else 0.52,
            retest_quality_score=round(retest_quality, 4),
            follow_through_score=round(follow_through, 4),
        )

    def _force_close_trade(self, trade: SimulatedTrade, exit_price: float) -> SimulatedTrade:
        if trade.remaining_notional_usdt > 0:
            trade.realized_pnl_usdt += self.simulator._pnl_for_fraction(
                trade.direction,
                trade.entry,
                exit_price,
                trade.remaining_notional_usdt,
            )
        trade.remaining_notional_usdt = 0
        trade.remaining_size_pct = 0
        trade.unrealized_pnl_usdt = 0
        trade.pnl_usdt = trade.realized_pnl_usdt
        trade.last_price = exit_price
        trade.status = "closed"
        trade.closed_at = trade.updated_at
        trade.exit_reason = trade.exit_reason or "time window expired"
        return trade

    @staticmethod
    def _result_from_trade(trade: SimulatedTrade) -> TradeReplayResult:
        risk_budget = trade.notional_usdt * abs(trade.entry - trade.initial_stop_loss) / max(trade.entry, 1e-9)
        rr = round(trade.realized_pnl_usdt / risk_budget, 4) if risk_budget else 0.0
        closed_at = trade.closed_at or trade.updated_at
        hold_hours = max((closed_at - trade.opened_at).total_seconds() / 3600, 0)
        break_even_exit = (
            trade.break_even_armed
            and trade.exit_reason is not None
            and "stop" in trade.exit_reason
            and abs(rr) <= 0.25
        )
        return TradeReplayResult(
            rr=rr,
            is_win=rr > 0,
            hold_hours=round(hold_hours, 4),
            tp1_hit=trade.tp1_hit,
            tp2_hit=trade.tp2_hit,
            break_even_exit=break_even_exit,
        )

    @staticmethod
    def _primary_symbol(card: StrategyCard, post: RawKOLPost) -> str | None:
        if post.symbols:
            return post.symbols[0]
        if card.preferred_symbols:
            return card.preferred_symbols[0]
        return None

    @staticmethod
    def _infer_direction(card: StrategyCard) -> str:
        return "short" if card.market == "bearish" else "long"

    @staticmethod
    def _infer_structure(card: StrategyCard) -> StructureType:
        conditions = set(card.entry_conditions)
        if "breakout" in conditions:
            return StructureType.BREAKOUT
        if "pullback_confirmation" in conditions:
            return StructureType.PULLBACK
        if "sentiment_tailwind" in conditions:
            return StructureType.MOMENTUM
        return StructureType.UNKNOWN

    @staticmethod
    def _find_entry_index(klines: list[list], created_at: datetime) -> int | None:
        target_ms = int(created_at.astimezone(UTC).timestamp() * 1000)
        for idx, candle in enumerate(klines):
            if int(candle[0]) <= target_ms <= int(candle[6]):
                return idx
        return None

    @staticmethod
    def _records_to_posts(records) -> list[RawKOLPost]:
        posts: list[RawKOLPost] = []
        for record in records:
            posts.append(
                RawKOLPost(
                    author=record.author,
                    text=record.text,
                    created_at=StrategyBacktester._coerce_datetime(record.created_at)
                    or StrategyBacktester._coerce_datetime(record.imported_at),
                    url=record.url,
                    likes=record.likes,
                    reposts=record.reposts,
                    replies=record.replies,
                    views=record.views,
                    symbols=[symbol for symbol in record.symbols.split(",") if symbol],
                    tags=[tag for tag in record.tags.split(",") if tag],
                    source=record.source,
                )
            )
        return posts

    @staticmethod
    def _coerce_datetime(value) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _candle_open_datetime(candle: list) -> datetime:
        return datetime.fromtimestamp(int(candle[0]) / 1000, tz=UTC)

    @staticmethod
    def _candle_close_datetime(candle: list) -> datetime:
        return datetime.fromtimestamp(int(candle[6]) / 1000, tz=UTC)

    @staticmethod
    def _max_drawdown_rr(rr_values: list[float]) -> float:
        if not rr_values:
            return 0.0
        peak = 0.0
        equity = 0.0
        max_drawdown = 0.0
        for rr in rr_values:
            equity += rr
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, equity - peak)
        return round(max_drawdown, 4)


def _replace_tier_tags(tags: list[str], tier: str) -> list[str]:
    filtered = [tag for tag in tags if tag not in {"tier:core", "tier:candidate", "tier:watchlist"}]
    filtered.append(f"tier:{tier}")
    return filtered
