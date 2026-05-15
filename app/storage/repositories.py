import json
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.core.simulator import SimulatedTrade
from app.data.schema import TradeSignal
from app.storage.models import (
    KOLPostRecord,
    SignalRecord,
    SimTradeRecord,
    StrategyMetricRecord,
    TradeFeeRecord,
    TradeJournalRecord,
)


class SignalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_signal(self, signal: TradeSignal) -> SignalRecord:
        record = SignalRecord(
            symbol=signal.symbol,
            direction=signal.direction.value,
            confidence=signal.confidence,
            rr=signal.rr,
            score=signal.score,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            structure=signal.structure.value,
            reasons="\n".join(signal.reasons),
            primary_strategy_name=signal.primary_strategy_name,
            matched_strategy_names="\n".join(signal.matched_strategy_names),
            created_at=signal.created_at,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_signals(self, limit: int = 50) -> list[SignalRecord]:
        statement = select(SignalRecord).order_by(SignalRecord.created_at.desc()).limit(limit)
        return list(self.session.exec(statement).all())

    def delete_all(self) -> int:
        records = list(self.session.exec(select(SignalRecord)).all())
        count = len(records)
        for record in records:
            self.session.delete(record)
        self.session.commit()
        return count


class TradeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_trade(self, trade: SimulatedTrade) -> SimulatedTrade:
        record = SimTradeRecord(**self._to_record_payload(trade))
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_trade_model(record)

    def update_trade(self, trade: SimulatedTrade) -> SimulatedTrade:
        existing = self.session.get(SimTradeRecord, trade.id)
        if existing is None:
            return self.save_trade(trade)
        for key, value in self._to_record_payload(trade).items():
            setattr(existing, key, value)
        self.session.add(existing)
        self.session.commit()
        self.session.refresh(existing)
        return self._to_trade_model(existing)

    def list_open_trades(self) -> list[SimulatedTrade]:
        statement = select(SimTradeRecord).where(
            SimTradeRecord.status.in_(["pending_entry", "open", "partial"])
        )
        return [self._to_trade_model(record) for record in self.session.exec(statement).all()]

    def list_all_trades(self, limit: int = 100) -> list[SimulatedTrade]:
        statement = select(SimTradeRecord).order_by(SimTradeRecord.opened_at.desc()).limit(limit)
        return [self._to_trade_model(record) for record in self.session.exec(statement).all()]

    def list_recent_closed_trades(self, limit: int = 20) -> list[SimulatedTrade]:
        statement = (
            select(SimTradeRecord)
            .where(SimTradeRecord.status.in_(["closed", "cancelled"]))
            .order_by(SimTradeRecord.updated_at.desc())
            .limit(limit)
        )
        return [self._to_trade_model(record) for record in self.session.exec(statement).all()]

    def delete_all(self) -> int:
        records = list(self.session.exec(select(SimTradeRecord)).all())
        count = len(records)
        for record in records:
            self.session.delete(record)
        self.session.commit()
        return count

    @staticmethod
    def _to_record_payload(trade: SimulatedTrade) -> dict:
        payload = trade.model_dump()
        payload["management_plan"] = "\n".join(trade.management_plan)
        payload["matched_strategy_names"] = "\n".join(trade.matched_strategy_names)
        return payload

    @staticmethod
    def _to_trade_model(record: SimTradeRecord) -> SimulatedTrade:
        payload = record.model_dump()
        payload["opened_at"] = TradeRepository._ensure_utc_datetime(
            payload.get("opened_at") or payload.get("updated_at") or datetime.now(UTC)
        )
        payload["updated_at"] = TradeRepository._ensure_utc_datetime(
            payload.get("updated_at") or payload["opened_at"]
        )
        if payload.get("closed_at") is not None:
            payload["closed_at"] = TradeRepository._ensure_utc_datetime(payload["closed_at"])
        payload["management_plan"] = [
            item for item in (payload.get("management_plan") or "").splitlines() if item.strip()
        ]
        payload["matched_strategy_names"] = [
            item for item in (payload.get("matched_strategy_names") or "").splitlines() if item.strip()
        ]
        return SimulatedTrade(**payload)

    @staticmethod
    def _ensure_utc_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class TradeJournalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def log_event(
        self,
        symbol: str,
        event_type: str,
        message: str,
        trade_id: str | None = None,
        status: str = "info",
        details: dict | None = None,
    ) -> TradeJournalRecord:
        record = TradeJournalRecord(
            trade_id=trade_id,
            symbol=symbol,
            event_type=event_type,
            status=status,
            message=message,
            details=json.dumps(details or {}, ensure_ascii=True),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_events(self, limit: int = 100) -> list[TradeJournalRecord]:
        statement = select(TradeJournalRecord).order_by(TradeJournalRecord.created_at.desc()).limit(limit)
        return list(self.session.exec(statement).all())

    def count_recent_actions(self, window_minutes: int, event_types: list[str] | None = None) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
        statement = select(TradeJournalRecord).where(TradeJournalRecord.created_at >= cutoff)
        if event_types:
            statement = statement.where(TradeJournalRecord.event_type.in_(event_types))
        return len(list(self.session.exec(statement).all()))

    def delete_all(self) -> int:
        records = list(self.session.exec(select(TradeJournalRecord)).all())
        count = len(records)
        for record in records:
            self.session.delete(record)
        self.session.commit()
        return count


class TradeFeeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def log_fee(self, *, trade_id: str | None, symbol: str, event_type: str, amount_usdt: float) -> TradeFeeRecord:
        record = TradeFeeRecord(
            trade_id=trade_id,
            symbol=symbol,
            event_type=event_type,
            amount_usdt=amount_usdt,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_all(self) -> list[TradeFeeRecord]:
        statement = select(TradeFeeRecord).order_by(TradeFeeRecord.created_at.desc())
        return list(self.session.exec(statement).all())

    def sum_since(self, cutoff: datetime) -> float:
        records = self.session.exec(select(TradeFeeRecord).where(TradeFeeRecord.created_at >= cutoff)).all()
        return round(sum(record.amount_usdt for record in records), 6)

    def sum_all(self) -> float:
        records = self.session.exec(select(TradeFeeRecord)).all()
        return round(sum(record.amount_usdt for record in records), 6)

    def delete_all(self) -> int:
        records = list(self.session.exec(select(TradeFeeRecord)).all())
        count = len(records)
        for record in records:
            self.session.delete(record)
        self.session.commit()
        return count


class KOLPostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_post(
        self,
        strategy_name: str,
        author: str,
        source: str,
        text: str,
        created_at=None,
        url: str | None = None,
        likes: int = 0,
        reposts: int = 0,
        replies: int = 0,
        views: int = 0,
        symbols: list[str] | None = None,
        tags: list[str] | None = None,
        raw_payload: str = "",
    ) -> KOLPostRecord:
        record = KOLPostRecord(
            strategy_name=strategy_name,
            author=author,
            source=source,
            text=text,
            created_at=created_at,
            url=url,
            likes=likes,
            reposts=reposts,
            replies=replies,
            views=views,
            symbols=",".join(symbols or []),
            tags=",".join(tags or []),
            raw_payload=raw_payload,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_posts(self, strategy_name: str | None = None) -> list[KOLPostRecord]:
        statement = select(KOLPostRecord)
        if strategy_name:
            statement = statement.where(KOLPostRecord.strategy_name == strategy_name)
        statement = statement.order_by(KOLPostRecord.imported_at.asc())
        seen: set[str] = set()
        unique_posts: list[KOLPostRecord] = []
        for record in self.session.exec(statement).all():
            fingerprint = record.raw_payload or f"{record.strategy_name}|{record.author}|{record.created_at}|{record.text}"
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique_posts.append(record)
        return unique_posts


class StrategyMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        strategy_name: str,
        sample_size: int,
        win_rate: float,
        avg_rr: float,
        total_rr: float,
        wins: int,
        losses: int,
        avg_hold_hours: float = 0,
        tp1_hit_rate: float = 0,
        tp2_hit_rate: float = 0,
        breakeven_exit_rate: float = 0,
        max_drawdown_rr: float = 0,
    ) -> StrategyMetricRecord:
        statement = select(StrategyMetricRecord).where(StrategyMetricRecord.strategy_name == strategy_name)
        existing = self.session.exec(statement).first()
        if existing:
            existing.sample_size = sample_size
            existing.win_rate = win_rate
            existing.avg_rr = avg_rr
            existing.total_rr = total_rr
            existing.wins = wins
            existing.losses = losses
            existing.avg_hold_hours = avg_hold_hours
            existing.tp1_hit_rate = tp1_hit_rate
            existing.tp2_hit_rate = tp2_hit_rate
            existing.breakeven_exit_rate = breakeven_exit_rate
            existing.max_drawdown_rr = max_drawdown_rr
            self.session.add(existing)
            self.session.commit()
            self.session.refresh(existing)
            return existing
        record = StrategyMetricRecord(
            strategy_name=strategy_name,
            sample_size=sample_size,
            win_rate=win_rate,
            avg_rr=avg_rr,
            total_rr=total_rr,
            wins=wins,
            losses=losses,
            avg_hold_hours=avg_hold_hours,
            tp1_hit_rate=tp1_hit_rate,
            tp2_hit_rate=tp2_hit_rate,
            breakeven_exit_rate=breakeven_exit_rate,
            max_drawdown_rr=max_drawdown_rr,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_all(self) -> list[StrategyMetricRecord]:
        return list(self.session.exec(select(StrategyMetricRecord)).all())

    def get_by_strategy_name(self, strategy_name: str) -> StrategyMetricRecord | None:
        statement = select(StrategyMetricRecord).where(StrategyMetricRecord.strategy_name == strategy_name)
        return self.session.exec(statement).first()
