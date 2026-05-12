from pathlib import Path

from app.data.schema import Candidate, MarketSnapshot
from app.knowledge.kol_import import RawKOLPost, extract_symbols_from_text, from_legacy_text
from app.knowledge.distiller import KolStrategyDistiller
from app.knowledge.prompt_builder import PromptBuilder
from app.knowledge.strategy_store import StrategyStore
from app.core.signal_engine import SignalEngine
from scripts.import_kol_posts import load_posts


def test_distiller_creates_rich_strategy_card():
    posts = [
        "BTCUSDT breakout with volume expansion and OI rising.",
        "Watch pullback on 4h support, avoid overheated funding.",
    ]
    card = KolStrategyDistiller().distill("alpha_alpha", posts, creator="tester")

    assert card.name == "alpha_alpha"
    assert "breakout" in card.entry_conditions
    assert card.creator == "tester"
    assert card.sample_size == 2
    assert card.tags
    assert card.source_posts == 2
    assert card.confidence_bias > 0


def test_strategy_store_round_trip_json_and_markdown(tmp_path: Path):
    store = StrategyStore(root=tmp_path)
    card = KolStrategyDistiller().distill("swing_style", ["ETHUSDT pullback on support"], creator="tester")

    json_path = store.save(card)
    md_path = store.save_markdown(card)

    loaded = store.load("swing_style")
    cards = store.list_cards()

    assert json_path.exists()
    assert md_path.exists()
    assert loaded is not None
    assert loaded.name == "swing_style"
    assert any(card.name == "swing_style" for card in cards)


def test_prompt_builder_uses_matching_cards():
    card = KolStrategyDistiller().distill("btc_trend", ["BTCUSDT breakout"], creator="tester")
    prompt = PromptBuilder().build_candidate_prompt(
        Candidate(snapshot=MarketSnapshot(symbol="BTCUSDT", price=100, quote_volume_24h=1_000_000), hard_score=50),
        [card],
    )

    assert "Relevant strategy cards" in prompt
    assert "btc_trend" in prompt


def test_signal_engine_applies_kol_card_bonus(tmp_path: Path):
    store = StrategyStore(root=tmp_path)
    card = KolStrategyDistiller().distill(
        "btc_booster",
        ["BTCUSDT breakout with volume expansion and OI rising"],
        creator="tester",
    )
    card.strategy_tier = "candidate"
    card.tier_score = 72.0
    store.save(card)

    engine = SignalEngine()
    engine.strategy_store = store
    candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT",
            price=100,
            price_change_pct_24h=5,
            quote_volume_24h=200_000_000,
            oi=1000,
            funding_rate=0.0001,
            btc_trend="up",
        ),
        hard_score=40,
    )

    engine._apply_kol_cards(candidate)

    assert candidate.hard_score > 40
    assert any(tag.startswith("kol:") for tag in candidate.tags)
    assert "strategy-tier:candidate" in candidate.tags


def test_signal_engine_prioritizes_core_cards_over_watchlist(tmp_path: Path):
    store = StrategyStore(root=tmp_path)

    core_card = KolStrategyDistiller().distill(
        "btc_core",
        ["BTCUSDT breakout with volume expansion and OI rising"],
        creator="tester",
    )
    core_card.strategy_tier = "core"
    core_card.tier_score = 98.0
    store.save(core_card)

    watchlist_card = KolStrategyDistiller().distill(
        "btc_watchlist",
        ["BTCUSDT breakout with volume expansion and OI rising"],
        creator="tester",
    )
    watchlist_card.strategy_tier = "watchlist"
    watchlist_card.tier_score = 18.0
    store.save(watchlist_card)

    engine = SignalEngine()
    engine.strategy_store = store

    core_candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT",
            price=100,
            price_change_pct_24h=5,
            quote_volume_24h=200_000_000,
            oi=1000,
            funding_rate=0.0001,
            btc_trend="up",
        ),
        hard_score=40,
    )
    watchlist_candidate = Candidate.model_validate(core_candidate.model_dump())

    engine.strategy_store = StrategyStore(root=tmp_path / "core_only")
    engine.strategy_store.save(core_card)
    engine._apply_kol_cards(core_candidate)

    engine.strategy_store = StrategyStore(root=tmp_path / "watch_only")
    engine.strategy_store.save(watchlist_card)
    engine._apply_kol_cards(watchlist_candidate)

    assert core_candidate.hard_score > watchlist_candidate.hard_score
    assert "strategy-tier:core" in core_candidate.tags
    assert "strategy-tier:watchlist" in watchlist_candidate.tags


def test_signal_engine_core_only_ignores_watchlist_cards(tmp_path: Path):
    store = StrategyStore(root=tmp_path)
    watchlist_card = KolStrategyDistiller().distill(
        "btc_watch_only",
        ["BTCUSDT breakout with volume expansion and OI rising"],
        creator="tester",
    )
    watchlist_card.strategy_tier = "watchlist"
    watchlist_card.tier_score = 24.0
    store.save(watchlist_card)

    engine = SignalEngine()
    engine.strategy_store = store
    candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT",
            price=100,
            price_change_pct_24h=5,
            quote_volume_24h=200_000_000,
            oi=1000,
            funding_rate=0.0001,
            btc_trend="up",
        ),
        hard_score=40,
    )

    strategy_matches = engine._apply_kol_cards(candidate, strategy_tier_mode="core-only")

    assert strategy_matches == []
    assert candidate.hard_score == 40


def test_raw_kol_post_helpers():
    post = RawKOLPost(author="tester", text="BTCUSDT breakout and ETHUSDT pullback", created_at="2026-04-17T13:32:00Z")
    legacy = from_legacy_text("SOLUSDT breakout")

    assert post.author == "tester"
    assert "BTCUSDT" in post.symbols
    assert "ETHUSDT" in post.symbols
    assert legacy.source == "text"
    assert "SOLUSDT" in legacy.symbols
    assert extract_symbols_from_text("DOGEUSDT breakout") == ["DOGEUSDT"]


def test_loader_supports_json_and_text(tmp_path: Path):
    json_file = tmp_path / "posts.json"
    json_file.write_text(
        """
[
  {"author": "a", "text": "BTCUSDT breakout", "created_at": "2026-04-17T13:32:00Z"},
  {"author": "b", "text": "ETHUSDT pullback"}
]
""".strip(),
        encoding="utf-8",
    )
    txt_file = tmp_path / "posts.txt"
    txt_file.write_text("tester | 2026-04-17T13:32:00Z | SOLUSDT breakout", encoding="utf-8")

    json_posts = load_posts(json_file, "json")
    txt_posts = load_posts(txt_file, "txt")

    assert len(json_posts) == 2
    assert json_posts[0].author == "a"
    assert txt_posts[0].author == "tester"
