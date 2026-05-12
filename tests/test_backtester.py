from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from app.knowledge.backtester import StrategyBacktester
from app.knowledge.distiller import KolStrategyDistiller
from app.knowledge.kol_import import RawKOLPost
from app.knowledge.strategy_store import StrategyStore
from app.storage.db import engine, init_db
from app.storage.repositories import KOLPostRepository, StrategyMetricRepository


class FakeBinanceClient:
    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 48):
        open_time = int(datetime(2026, 4, 17, 13, tzinfo=UTC).timestamp() * 1000)
        return [
            [open_time + i * 3_600_000, "0", str(100 + i), str(99 - i * 0.2), str(100 + i * 0.5), "0", open_time + (i + 1) * 3_600_000 - 1]
            for i in range(48)
        ]


@pytest.mark.asyncio
async def test_backtester_calculates_metrics_and_updates_card(tmp_path):
    store = StrategyStore(root=tmp_path)
    card = KolStrategyDistiller().distill("btc_booster", ["BTCUSDT breakout with volume expansion"], creator="tester")
    store.save(card)
    store.save_markdown(card)

    init_db()
    posts = [
        RawKOLPost(
            author="kol",
            text="BTCUSDT breakout with volume expansion",
            created_at="2026-04-17T13:00:00Z",
            symbols=["BTCUSDT"],
        )
    ]

    with Session(engine) as session:
        repo = KOLPostRepository(session)
        for post in posts:
            repo.save_post(
                strategy_name="btc_booster",
                author=post.author,
                source=post.source,
                text=post.text,
                created_at=post.created_at,
                symbols=post.symbols,
                tags=post.tags,
                raw_payload=post.model_dump_json(),
            )

        backtester = StrategyBacktester(client=FakeBinanceClient(), store=store)
        outcomes = await backtester.update_store_metrics(session)
        metrics = StrategyMetricRepository(session).list_all()

    assert outcomes[0].strategy_name == "btc_booster"
    assert outcomes[0].sample_size == 1
    assert outcomes[0].tp1_hit_rate >= 0
    assert outcomes[0].avg_hold_hours >= 0
    assert metrics[0].strategy_name == "btc_booster"
    assert metrics[0].sample_size == 1
    assert metrics[0].tp1_hit_rate >= 0
