from app.knowledge.kol_import import RawKOLPost
from app.knowledge.kol_pipeline import KOLPipeline


def test_kol_pipeline_deduplicates_and_filters():
    posts = [
        RawKOLPost(author="a", text="BTCUSDT breakout on volume and OI rising", symbols=["BTCUSDT"]),
        RawKOLPost(author="a", text="BTCUSDT breakout on volume and OI rising", symbols=["BTCUSDT"]),
        RawKOLPost(author="b", text="gm frens", symbols=[]),
    ]

    pipeline = KOLPipeline()
    result = pipeline.run(posts)

    assert len(result.kept_posts) == 1
    assert len(result.rejected_posts) == 1
    assert len(result.cards) == 1
    assert result.cards[0].source_posts == 1
