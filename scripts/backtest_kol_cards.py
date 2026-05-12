import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.backtester import StrategyBacktester
from app.storage.db import init_db, engine
from sqlmodel import Session


def main() -> None:
    init_db()
    async def run():
        with Session(engine) as session:
            return await StrategyBacktester().update_store_metrics(session)

    outcomes = asyncio.run(run())
    for outcome in outcomes:
        print(
            f"{outcome.strategy_name}: samples={outcome.sample_size}, wins={outcome.wins}, "
            f"losses={outcome.losses}, win_rate={outcome.win_rate:.2%}, avg_rr={outcome.avg_rr:.2f}, "
            f"avg_hold_hours={outcome.avg_hold_hours:.2f}, tp1_hit_rate={outcome.tp1_hit_rate:.2%}, "
            f"tp2_hit_rate={outcome.tp2_hit_rate:.2%}, breakeven_exit_rate={outcome.breakeven_exit_rate:.2%}, "
            f"max_drawdown_rr={outcome.max_drawdown_rr:.2f}"
        )


if __name__ == "__main__":
    main()
