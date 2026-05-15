from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, create_engine

from app.config import Settings, get_settings
from app.storage.models import SimTradeRecord, TradeFeeRecord, TradeJournalRecord


def build_engine(settings: Settings | None = None):
    settings = settings or get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


engine = build_engine()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_sqlite_trade_columns()
    _ensure_sqlite_signal_columns()
    _ensure_sqlite_strategy_metric_columns()
    _ensure_sqlite_trade_journal_columns()
    _ensure_sqlite_trade_fee_columns()


def get_session():
    with Session(engine) as session:
        yield session


def _ensure_sqlite_trade_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    table_name = SimTradeRecord.__tablename__
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    desired_columns = {
        "structure": "TEXT DEFAULT 'unknown'",
        "quantity": "FLOAT DEFAULT 0",
        "remaining_notional_usdt": "FLOAT DEFAULT 0",
        "remaining_quantity": "FLOAT DEFAULT 0",
        "initial_stop_loss": "FLOAT DEFAULT 0",
        "current_stop_loss": "FLOAT DEFAULT 0",
        "tp1_price": "FLOAT DEFAULT 0",
        "tp2_price": "FLOAT DEFAULT 0",
        "tp1_hit": "BOOLEAN DEFAULT 0",
        "tp2_hit": "BOOLEAN DEFAULT 0",
        "tp1_size_pct": "FLOAT DEFAULT 0.4",
        "tp2_size_pct": "FLOAT DEFAULT 0.35",
        "remaining_size_pct": "FLOAT DEFAULT 1.0",
        "entry_mode": "TEXT DEFAULT 'market'",
        "entry_confirmed": "BOOLEAN DEFAULT 1",
        "confirmation_required": "BOOLEAN DEFAULT 0",
        "break_even_armed": "BOOLEAN DEFAULT 0",
        "trail_active": "BOOLEAN DEFAULT 0",
        "updated_at": "TIMESTAMP",
        "last_price": "FLOAT",
        "max_price_seen": "FLOAT",
        "min_price_seen": "FLOAT",
        "realized_pnl_usdt": "FLOAT DEFAULT 0",
        "unrealized_pnl_usdt": "FLOAT DEFAULT 0",
        "fees_paid_usdt": "FLOAT DEFAULT 0",
        "exit_reason": "TEXT",
        "management_plan": "TEXT DEFAULT ''",
        "primary_strategy_name": "TEXT",
        "matched_strategy_names": "TEXT DEFAULT ''",
    }

    with engine.begin() as connection:
        for column_name, column_type in desired_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def _ensure_sqlite_signal_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    table_name = "signalrecord"
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    desired_columns = {
        "primary_strategy_name": "TEXT",
        "matched_strategy_names": "TEXT DEFAULT ''",
    }

    with engine.begin() as connection:
        for column_name, column_type in desired_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def _ensure_sqlite_strategy_metric_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    table_name = "strategymetricrecord"
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    desired_columns = {
        "avg_hold_hours": "FLOAT DEFAULT 0",
        "tp1_hit_rate": "FLOAT DEFAULT 0",
        "tp2_hit_rate": "FLOAT DEFAULT 0",
        "breakeven_exit_rate": "FLOAT DEFAULT 0",
        "max_drawdown_rr": "FLOAT DEFAULT 0",
    }

    with engine.begin() as connection:
        for column_name, column_type in desired_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def _ensure_sqlite_trade_journal_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    table_name = TradeJournalRecord.__tablename__
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    desired_columns = {
        "trade_id": "TEXT",
        "symbol": "TEXT",
        "event_type": "TEXT",
        "status": "TEXT DEFAULT 'info'",
        "message": "TEXT DEFAULT ''",
        "details": "TEXT DEFAULT ''",
        "created_at": "TIMESTAMP",
    }

    with engine.begin() as connection:
        for column_name, column_type in desired_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def _ensure_sqlite_trade_fee_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    table_name = TradeFeeRecord.__tablename__
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    desired_columns = {
        "trade_id": "TEXT",
        "symbol": "TEXT",
        "event_type": "TEXT",
        "amount_usdt": "FLOAT DEFAULT 0",
        "created_at": "TIMESTAMP",
    }

    with engine.begin() as connection:
        for column_name, column_type in desired_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
