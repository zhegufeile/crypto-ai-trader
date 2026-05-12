import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.kol_import import RawKOLPost, from_legacy_text, extract_symbols_from_text
from app.knowledge.kol_pipeline import KOLPipeline
from app.knowledge.strategy_store import StrategyStore
from app.storage.db import init_db, engine
from app.storage.repositories import KOLPostRepository
from sqlmodel import Session


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the KOL pipeline: dedupe, filter, cluster, distill.")
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--input-format", choices=["auto", "json", "md", "txt"], default="auto")
    parser.add_argument("--persist", action="store_true", help="Persist raw posts and strategy cards.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output summary.")
    args = parser.parse_args()

    raw_posts = load_posts(args.input_file, args.input_format)
    pipeline = KOLPipeline()
    result = pipeline.run(raw_posts)

    if args.persist:
        persist_pipeline_result(result.cards, result.kept_posts)

    summary = {
        "input_posts": len(raw_posts),
        "unique_posts": len(pipeline.deduplicate(raw_posts)),
        "kept_posts": len(result.kept_posts),
        "rejected_posts": len(result.rejected_posts),
        "clusters": len(result.clusters),
        "cards": len(result.cards),
        "card_names": [card.name for card in result.cards],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def load_posts(path: Path, input_format: str = "auto") -> list[RawKOLPost]:
    suffix = path.suffix.lower()
    mode = input_format if input_format != "auto" else suffix.lstrip(".")
    if mode == "json":
        return _load_json_posts(path)
    if mode in {"md", "txt"}:
        return _load_text_posts(path)
    return [from_legacy_text(path.read_text(encoding="utf-8"), source="legacy_text")]


def _load_json_posts(path: Path) -> list[RawKOLPost]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("posts", [])
    posts: list[RawKOLPost] = []
    for item in payload:
        if isinstance(item, RawKOLPost):
            posts.append(item)
        elif isinstance(item, str):
            posts.append(from_legacy_text(item))
        elif isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            author = str(item.get("author", "unknown"))
            symbols = item.get("symbols") or extract_symbols_from_text(text)
            posts.append(
                RawKOLPost(
                    author=author,
                    text=text,
                    created_at=item.get("created_at"),
                    url=item.get("url"),
                    likes=int(item.get("likes", 0) or 0),
                    reposts=int(item.get("reposts", 0) or 0),
                    replies=int(item.get("replies", 0) or 0),
                    views=int(item.get("views", 0) or 0),
                    symbols=[str(symbol).upper() for symbol in symbols],
                    tags=[str(tag) for tag in item.get("tags", [])] if item.get("tags") else [],
                    source=str(item.get("source", "x")),
                )
            )
    return posts


def _load_text_posts(path: Path) -> list[RawKOLPost]:
    posts: list[RawKOLPost] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        if "|" in text:
            posts.append(_parse_pipe_line(text))
        else:
            posts.append(from_legacy_text(text))
    return posts


def _parse_pipe_line(line: str) -> RawKOLPost:
    parts = [part.strip() for part in line.split("|")]
    author = parts[0] if parts else "unknown"
    created_at = parts[1] if len(parts) > 2 else None
    text = parts[-1] if len(parts) >= 2 else line
    symbols = extract_symbols_from_text(text)
    return RawKOLPost(author=author or "unknown", created_at=created_at, text=text, symbols=symbols, source="text")


def persist_pipeline_result(cards, posts) -> None:
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
