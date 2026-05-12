from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.scheduler import run_scan_once
from app.knowledge.distiller import KolStrategyDistiller
from app.knowledge.strategy_store import StrategyStore
from app.main import app
from app.storage.db import engine, init_db
from app.storage.repositories import StrategyMetricRepository


def test_strategy_cards_api_returns_metrics(tmp_path, monkeypatch):
    store = StrategyStore(root=tmp_path)
    card = KolStrategyDistiller().distill("api_card", ["BTCUSDT breakout with volume"], creator="tester")
    store.save(card)

    init_db()
    with Session(engine) as session:
        StrategyMetricRepository(session).upsert(
            strategy_name="api_card",
            sample_size=12,
            win_rate=0.75,
            avg_rr=2.4,
            total_rr=28.8,
            wins=9,
            losses=3,
            avg_hold_hours=6.5,
            tp1_hit_rate=0.66,
            tp2_hit_rate=0.42,
            breakeven_exit_rate=0.16,
            max_drawdown_rr=-1.4,
        )

    monkeypatch.setattr("app.api.routes_strategy_cards.StrategyStore", lambda: store)
    client = TestClient(app)

    response = client.get("/strategy-cards")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["name"] == "api_card"
    assert payload[0]["sample_size"] == 12
    assert payload[0]["historical_win_rate"] == 0.75
    assert payload[0]["historical_rr"] == 2.4
    assert payload[0]["tp1_hit_rate"] == 0.66
    assert payload[0]["avg_hold_hours"] == 6.5
    assert payload[0]["strategy_tier"] in {"core", "candidate", "watchlist"}


def test_strategy_card_detail_api_returns_single_card(tmp_path, monkeypatch):
    store = StrategyStore(root=tmp_path)
    card = KolStrategyDistiller().distill("detail_card", ["ETHUSDT pullback"], creator="tester")
    store.save(card)

    monkeypatch.setattr("app.api.routes_strategy_cards.StrategyStore", lambda: store)
    client = TestClient(app)

    response = client.get("/strategy-cards/detail_card")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "detail_card"
    assert payload["entry_conditions"]
    assert payload["strategy_tier"] in {"core", "candidate", "watchlist"}


def test_strategy_card_leaderboard_returns_ranked_cards(tmp_path, monkeypatch):
    store = StrategyStore(root=tmp_path)
    strong = KolStrategyDistiller().distill("strong_card", ["BTCUSDT breakout with volume"], creator="tester")
    weak = KolStrategyDistiller().distill("weak_card", ["ETHUSDT pullback"], creator="tester")
    store.save(strong)
    store.save(weak)

    init_db()
    with Session(engine) as session:
        repo = StrategyMetricRepository(session)
        repo.upsert(
            strategy_name="strong_card",
            sample_size=12,
            win_rate=0.72,
            avg_rr=2.6,
            total_rr=31.2,
            wins=9,
            losses=3,
            avg_hold_hours=7,
            tp1_hit_rate=0.75,
            tp2_hit_rate=0.45,
            breakeven_exit_rate=0.10,
            max_drawdown_rr=-1.1,
        )
        repo.upsert(
            strategy_name="weak_card",
            sample_size=5,
            win_rate=0.4,
            avg_rr=1.2,
            total_rr=6.0,
            wins=2,
            losses=3,
            avg_hold_hours=4,
            tp1_hit_rate=0.30,
            tp2_hit_rate=0.10,
            breakeven_exit_rate=0.30,
            max_drawdown_rr=-2.6,
        )

    monkeypatch.setattr("app.api.routes_strategy_cards.StrategyStore", lambda: store)
    client = TestClient(app)

    response = client.get("/strategy-cards/leaderboard?limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["name"] == "strong_card"
    assert payload[0]["tier"] in {"core", "candidate"}
    assert payload[0]["rank_score"] >= payload[1]["rank_score"]
