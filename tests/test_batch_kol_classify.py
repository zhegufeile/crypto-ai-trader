from pathlib import Path

from app.knowledge.kol_import import RawKOLPost
from app.knowledge.kol_pipeline import KOLPipeline
from app.knowledge.distiller import StrategyCard
from scripts.batch_kol_classify import expand_inputs, filter_strategy_cards, write_kol_notes


def test_expand_inputs_handles_files_and_directories(tmp_path: Path):
    folder = tmp_path / "kol"
    folder.mkdir()
    a = folder / "a.json"
    b = folder / "b.csv"
    a.write_text("[]", encoding="utf-8")
    b.write_text("[]", encoding="utf-8")
    single = tmp_path / "single.txt"
    single.write_text("x", encoding="utf-8")

    files = expand_inputs([folder, single])

    assert a in files
    assert b in files
    assert single in files


def test_write_kol_notes_creates_author_markdown(tmp_path: Path):
    posts = [
        RawKOLPost(
            author="Arya_web3",
            text="BTCUSDT breakout with volume and OI rising",
            created_at="2026-04-17T13:32:00Z",
            symbols=["BTCUSDT"],
            likes=10,
        )
    ]
    result = KOLPipeline().run(posts)
    notes = write_kol_notes(
        notes_dir=tmp_path,
        author_posts={"Arya_web3": result.kept_posts},
        author_cards={"Arya_web3": result.cards},
        author_files={"Arya_web3": {"arya.json"}},
    )

    assert len(notes) == 1
    note = Path(notes[0])
    assert note.exists()
    content = note.read_text(encoding="utf-8")
    assert "# Arya_web3" in content
    assert "BTCUSDT" in content
    assert "Strategy Cards" in content


def test_filter_strategy_cards_keeps_only_high_quality_cards():
    keep = StrategyCard(
        name="arya_btc",
        description="btc breakout setup",
        market="bullish",
        timeframe="intraday",
        creator="Arya_web3",
        entry_conditions=["breakout", "oi_rising"],
        exit_conditions=["target_reached"],
        source_posts=6,
    )
    too_small = keep.model_copy(update={"name": "arya_sol", "source_posts": 2})
    manual = keep.model_copy(update={"name": "arya_lab", "entry_conditions": ["manual_review_required"]})
    too_long = keep.model_copy(
        update={"name": "arya_130_150_将可能进入严重经济风险阈值_引发全球通胀反弹_增长放缓甚至衰退"}
    )

    cards = filter_strategy_cards([too_small, manual, too_long, keep], min_source_posts=5)

    assert [card.name for card in cards] == ["arya_btc"]
