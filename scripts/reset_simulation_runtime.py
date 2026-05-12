from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.storage.db import engine, init_db
from app.storage.repositories import SignalRepository, TradeJournalRepository, TradeRepository


def main() -> None:
    init_db()
    with Session(engine) as session:
        result = {
            "status": "ok",
            "signals_deleted": SignalRepository(session).delete_all(),
            "positions_deleted": TradeRepository(session).delete_all(),
            "journal_deleted": TradeJournalRepository(session).delete_all(),
        }
    print(result)


if __name__ == "__main__":
    main()
