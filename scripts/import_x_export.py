import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.x_client import XExportAdapter
from app.knowledge.kol_pipeline import KOLPipeline
from app.knowledge.strategy_store import StrategyStore
from app.storage.db import engine, init_db
from app.storage.repositories import KOLPostRepository
from sqlmodel import Session


def main() -> None:
    parser = argparse.ArgumentParser(description="Import X/Twitter export files into the KOL pipeline.")
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--input-format", choices=["auto", "json", "csv", "txt", "md"], default="auto")
    parser.add_argument("--persist", action="store_true", help="Persist normalized posts and cards.")
    args = parser.parse_args()

    adapter = XExportAdapter()
    raw_posts = adapter.load_raw_posts(args.input_file, args.input_format)
    pipeline = KOLPipeline()
    result = pipeline.run(raw_posts)

    if args.persist:
        persist_result(result.kept_posts, result.cards)

    print(
        {
            "input_posts": len(raw_posts),
            "unique_posts": len(pipeline.deduplicate(raw_posts)),
            "kept_posts": len(result.kept_posts),
            "rejected_posts": len(result.rejected_posts),
            "clusters": len(result.clusters),
            "cards": len(result.cards),
            "card_names": [card.name for card in result.cards],
        }
    )


def persist_result(posts, cards) -> None:
    init_db()
    with Session(engine) as session:
        repo = KOLPostRepository(session)
        for post in posts:
            repo.save_post(
                strategy_name=post.author,
                author=post.author,
                source=post.source,
                text=post.text,
                created_at=post.created_at,
                url=post.url,
                likes=post.likes,
                reposts=post.reposts,
                replies=post.replies,
                views=post.views,
                symbols=post.symbols,
                tags=post.tags,
                raw_payload=post.model_dump_json(),
            )
    store = StrategyStore()
    for card in cards:
        store.save(card)
        store.save_markdown(card)


if __name__ == "__main__":
    main()
