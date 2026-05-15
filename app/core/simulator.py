from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.data.schema import MarketSnapshot, TradeSignal


ACTIVE_TRADE_STATUSES = {"pending_entry", "open", "partial"}
FINAL_TRADE_STATUSES = {"closed", "cancelled"}


class SimulatedTrade(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    direction: str
    structure: str
    entry: float
    stop_loss: float
    take_profit: float
    notional_usdt: float
    quantity: float = 0
    remaining_notional_usdt: float
    remaining_quantity: float = 0
    initial_stop_loss: float
    current_stop_loss: float
    tp1_price: float
    tp2_price: float
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp1_size_pct: float = 0.40
    tp2_size_pct: float = 0.35
    remaining_size_pct: float = 1.0
    status: str = "open"
    entry_mode: str = "market"
    entry_confirmed: bool = True
    confirmation_required: bool = False
    break_even_armed: bool = False
    trail_active: bool = False
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime | None = None
    last_price: float | None = None
    max_price_seen: float | None = None
    min_price_seen: float | None = None
    pnl_usdt: float = 0
    realized_pnl_usdt: float = 0
    unrealized_pnl_usdt: float = 0
    fees_paid_usdt: float = 0
    exit_reason: str | None = None
    management_plan: list[str] = Field(default_factory=list)
    primary_strategy_name: str | None = None
    matched_strategy_names: list[str] = Field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_TRADE_STATUSES


class Simulator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def open_trade(self, signal: TradeSignal, notional_usdt: float) -> SimulatedTrade:
        confirmation_required = signal.structure.value in {"breakout", "momentum"}
        if self.settings.live_force_immediate_entry_for_testing:
            confirmation_required = False
        entry_mode = "confirm_breakout_hold" if confirmation_required else "market"
        risk_unit = abs(signal.entry - signal.stop_loss)
        tp1_price = self._offset_price(signal.entry, signal.direction.value, risk_unit * 1.0)
        tp2_price = self._offset_price(signal.entry, signal.direction.value, risk_unit * 2.0)
        now = datetime.now(UTC)
        trade = SimulatedTrade(
            symbol=signal.symbol,
            direction=signal.direction.value,
            structure=signal.structure.value,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            notional_usdt=notional_usdt,
            quantity=round(notional_usdt / signal.entry, 8) if signal.entry else 0,
            remaining_notional_usdt=notional_usdt,
            remaining_quantity=round(notional_usdt / signal.entry, 8) if signal.entry else 0,
            initial_stop_loss=signal.stop_loss,
            current_stop_loss=signal.stop_loss,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            status="pending_entry" if confirmation_required else "open",
            entry_mode=entry_mode,
            entry_confirmed=not confirmation_required,
            confirmation_required=confirmation_required,
            opened_at=now,
            updated_at=now,
            last_price=signal.entry,
            max_price_seen=signal.entry,
            min_price_seen=signal.entry,
            management_plan=signal.management_plan,
            primary_strategy_name=signal.primary_strategy_name,
            matched_strategy_names=signal.matched_strategy_names,
        )
        if not confirmation_required and self.settings.use_simulation:
            self._charge_fee(trade, notional_usdt)
        return trade

    def update_trade(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> SimulatedTrade:
        if not trade.is_active:
            return trade

        price = snapshot.price
        trade.updated_at = datetime.now(UTC)
        trade.last_price = price
        trade.max_price_seen = price if trade.max_price_seen is None else max(trade.max_price_seen, price)
        trade.min_price_seen = price if trade.min_price_seen is None else min(trade.min_price_seen, price)

        if trade.status == "pending_entry":
            return self._update_pending_trade(trade, snapshot)

        if self._has_security_exit(snapshot):
            self._close_trade(trade, price, "security risk invalidated the trade")
            return trade

        if self._follow_through_failed(trade, snapshot):
            self._close_trade(trade, price, "follow-through failed after entry")
            return trade

        self._check_take_profit_steps(trade, price)
        self._update_trailing_stop(trade, price)

        if self._stop_triggered(trade, price):
            self._close_trade(trade, trade.current_stop_loss, "stop loss or trailing stop hit")
            return trade

        if self._final_target_hit(trade, price):
            self._close_trade(trade, trade.take_profit, "final take profit hit")
            return trade

        trade.unrealized_pnl_usdt = self._pnl_for_fraction(
            trade.direction,
            trade.entry,
            price,
            trade.remaining_notional_usdt,
        )
        trade.pnl_usdt = trade.realized_pnl_usdt + trade.unrealized_pnl_usdt
        return trade

    def _update_pending_trade(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> SimulatedTrade:
        price = snapshot.price
        age_minutes = max((datetime.now(UTC) - trade.opened_at).total_seconds() / 60, 0)
        if age_minutes >= self.settings.pending_entry_timeout_minutes:
            self._cancel_trade(trade, "entry confirmation timed out")
            return trade
        if self._stop_triggered(trade, price):
            self._cancel_trade(trade, "setup failed before entry confirmation")
            return trade

        if self._entry_confirmation_passed(trade, snapshot):
            trade.status = "open"
            trade.entry_confirmed = True
            if self.settings.use_simulation:
                self._charge_fee(trade, trade.notional_usdt)
            trade.unrealized_pnl_usdt = self._pnl_for_fraction(
                trade.direction,
                trade.entry,
                price,
                trade.remaining_notional_usdt,
            )
            trade.pnl_usdt = trade.unrealized_pnl_usdt
            return trade

        trade.unrealized_pnl_usdt = 0
        trade.pnl_usdt = 0
        return trade

    def _entry_confirmation_passed(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> bool:
        if trade.direction == "long":
            price_ok = snapshot.price >= trade.entry
        else:
            price_ok = snapshot.price <= trade.entry
        follow_ok = snapshot.follow_through_score >= self.settings.min_follow_through_score
        retest_ok = snapshot.retest_quality_score >= self.settings.min_retest_quality_score
        return price_ok and (follow_ok or retest_ok)

    def _follow_through_failed(self, trade: SimulatedTrade, snapshot: MarketSnapshot) -> bool:
        if trade.structure not in {"breakout", "momentum"}:
            return False
        if trade.tp1_hit:
            return False
        weak_follow = snapshot.follow_through_score < 0.25
        if trade.direction == "long":
            return weak_follow and snapshot.price <= trade.entry * 0.998
        return weak_follow and snapshot.price >= trade.entry * 1.002

    def _check_take_profit_steps(self, trade: SimulatedTrade, price: float) -> None:
        if not trade.tp1_hit and self._price_reached(trade.direction, price, trade.tp1_price):
            self._take_partial_profit(trade, trade.tp1_size_pct, trade.tp1_price)
            trade.tp1_hit = True
            trade.break_even_armed = True
            trade.current_stop_loss = self._better_stop(trade.direction, trade.current_stop_loss, trade.entry)
            trade.status = "partial"

        if trade.tp1_hit and not trade.tp2_hit and self._price_reached(trade.direction, price, trade.tp2_price):
            self._take_partial_profit(trade, trade.tp2_size_pct, trade.tp2_price)
            trade.tp2_hit = True
            trade.trail_active = True
            buffered_stop = self._offset_price(
                trade.entry,
                trade.direction,
                abs(trade.tp1_price - trade.entry) * 0.35,
            )
            trade.current_stop_loss = self._better_stop(trade.direction, trade.current_stop_loss, buffered_stop)
            trade.status = "partial"

    def _update_trailing_stop(self, trade: SimulatedTrade, price: float) -> None:
        if not trade.trail_active:
            return
        trail_gap = abs(trade.entry - trade.initial_stop_loss) * 0.8
        if trail_gap <= 0:
            return
        candidate_stop = self._offset_price(price, trade.direction, -trail_gap)
        trade.current_stop_loss = self._better_stop(trade.direction, trade.current_stop_loss, candidate_stop)

    def _take_partial_profit(self, trade: SimulatedTrade, size_pct: float, exit_price: float) -> None:
        if trade.remaining_size_pct <= 0:
            return
        fill_pct = min(size_pct, trade.remaining_size_pct)
        closed_notional = trade.notional_usdt * fill_pct
        self._charge_fee(trade, closed_notional)
        trade.realized_pnl_usdt += self._pnl_for_fraction(
            trade.direction,
            trade.entry,
            exit_price,
            closed_notional,
        )
        trade.remaining_size_pct = round(max(0.0, trade.remaining_size_pct - fill_pct), 6)
        trade.remaining_notional_usdt = round(trade.notional_usdt * trade.remaining_size_pct, 6)
        trade.remaining_quantity = round(trade.quantity * trade.remaining_size_pct, 8)

    def _close_trade(self, trade: SimulatedTrade, exit_price: float, reason: str) -> None:
        if trade.remaining_notional_usdt > 0:
            self._charge_fee(trade, trade.remaining_notional_usdt)
            trade.realized_pnl_usdt += self._pnl_for_fraction(
                trade.direction,
                trade.entry,
                exit_price,
                trade.remaining_notional_usdt,
            )
        trade.remaining_notional_usdt = 0
        trade.remaining_quantity = 0
        trade.remaining_size_pct = 0
        trade.unrealized_pnl_usdt = 0
        trade.pnl_usdt = trade.realized_pnl_usdt
        trade.status = "closed"
        trade.closed_at = datetime.now(UTC)
        trade.exit_reason = reason

    def _cancel_trade(self, trade: SimulatedTrade, reason: str) -> None:
        trade.status = "cancelled"
        trade.closed_at = datetime.now(UTC)
        trade.exit_reason = reason
        trade.unrealized_pnl_usdt = 0
        trade.pnl_usdt = 0
        trade.remaining_quantity = 0

    def _charge_fee(self, trade: SimulatedTrade, notional_usdt: float) -> None:
        if notional_usdt <= 0:
            return
        trade.fees_paid_usdt = round(trade.fees_paid_usdt + notional_usdt * self.settings.simulation_fee_rate, 6)

    @staticmethod
    def _has_security_exit(snapshot: MarketSnapshot) -> bool:
        return (
            snapshot.onchain_honeypot
            or snapshot.onchain_is_safe_buy is False
            or str(snapshot.onchain_risk_level).upper() == "CRITICAL"
        )

    @staticmethod
    def _price_reached(direction: str, price: float, target: float) -> bool:
        if direction == "long":
            return price >= target
        return price <= target

    @staticmethod
    def _stop_triggered(trade: SimulatedTrade, price: float) -> bool:
        if trade.direction == "long":
            return price <= trade.current_stop_loss
        return price >= trade.current_stop_loss

    @staticmethod
    def _final_target_hit(trade: SimulatedTrade, price: float) -> bool:
        if trade.direction == "long":
            return price >= trade.take_profit
        return price <= trade.take_profit

    @staticmethod
    def _better_stop(direction: str, current_stop: float, candidate_stop: float) -> float:
        if direction == "long":
            return max(current_stop, candidate_stop)
        return min(current_stop, candidate_stop)

    @staticmethod
    def _offset_price(entry: float, direction: str, distance: float) -> float:
        if direction == "long":
            return entry + distance
        return entry - distance

    @staticmethod
    def _pnl_for_fraction(direction: str, entry: float, exit_price: float, notional_usdt: float) -> float:
        if entry == 0:
            return 0
        move_pct = (exit_price - entry) / entry
        if direction == "short":
            move_pct *= -1
        return round(notional_usdt * move_pct, 6)
