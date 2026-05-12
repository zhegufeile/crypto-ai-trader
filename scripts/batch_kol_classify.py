import argparse
import json
import re
import sys
from collections import Counter
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.x_client import XExportAdapter
from app.knowledge.kol_pipeline import KOLPipeline
from app.knowledge.strategy_store import StrategyStore
from app.storage.db import engine, init_db
from app.storage.repositories import KOLPostRepository
from sqlmodel import Session


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch classify 6 KOL export files and generate a report.")
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="KOL export files or folders. Supports JSON/CSV/TXT/MD exports.",
    )
    parser.add_argument("--input-format", choices=["auto", "json", "csv", "txt", "md"], default="auto")
    parser.add_argument("--persist", action="store_true", help="Persist normalized posts and strategy cards.")
    parser.add_argument("--output", type=Path, default=Path("kol_batch_report.json"))
    parser.add_argument("--notes-dir", type=Path, default=Path("obsidian/kol_notes"))
    parser.add_argument("--max-examples", type=int, default=8)
    parser.add_argument("--min-card-posts", type=int, default=5)
    args = parser.parse_args()

    files = expand_inputs(args.inputs)
    adapter = XExportAdapter()
    pipeline = KOLPipeline()
    init_db()

    report = {
        "files": [],
        "totals": {
            "input_posts": 0,
            "unique_posts": 0,
            "kept_posts": 0,
            "rejected_posts": 0,
            "clusters": 0,
            "cards": 0,
        },
        "top_symbols": [],
        "top_authors": [],
    }
    symbol_counter: Counter[str] = Counter()
    author_counter: Counter[str] = Counter()
    author_posts: dict[str, list] = defaultdict(list)
    author_cards: dict[str, list] = defaultdict(list)
    author_files: dict[str, set[str]] = defaultdict(set)

    with Session(engine) as session:
        repo = KOLPostRepository(session)
        store = StrategyStore()

        for file_path in files:
            raw_posts = adapter.load_raw_posts(file_path, args.input_format)
            result = pipeline.run(raw_posts)
            filtered_cards = filter_strategy_cards(result.cards, min_source_posts=args.min_card_posts)
            report["files"].append(
                {
                    "file": str(file_path),
                    "input_posts": len(raw_posts),
                    "unique_posts": len(pipeline.deduplicate(raw_posts)),
                    "kept_posts": len(result.kept_posts),
                    "rejected_posts": len(result.rejected_posts),
                    "clusters": len(result.clusters),
                    "cards": len(filtered_cards),
                    "raw_cards": len(result.cards),
                    "card_names": [card.name for card in filtered_cards],
                }
            )

            report["totals"]["input_posts"] += len(raw_posts)
            report["totals"]["unique_posts"] += len(pipeline.deduplicate(raw_posts))
            report["totals"]["kept_posts"] += len(result.kept_posts)
            report["totals"]["rejected_posts"] += len(result.rejected_posts)
            report["totals"]["clusters"] += len(result.clusters)
            report["totals"]["cards"] += len(filtered_cards)

            for post in result.kept_posts:
                author_counter[post.author] += 1
                author_posts[post.author].append(post)
                author_files[post.author].add(str(file_path))
                for symbol in post.symbols:
                    symbol_counter[symbol] += 1
            for card in filtered_cards:
                author_cards[card.creator].append(card)

            if args.persist:
                for post in result.kept_posts:
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
                for card in filtered_cards:
                    store.save(card)
                    store.save_markdown(card)

    report["top_symbols"] = symbol_counter.most_common(10)
    report["top_authors"] = author_counter.most_common(10)
    report["kol_notes"] = write_kol_notes(
        notes_dir=args.notes_dir,
        author_posts=author_posts,
        author_cards=author_cards,
        author_files=author_files,
        max_examples=args.max_examples,
    )
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def expand_inputs(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.iterdir() if p.is_file()))
        else:
            files.append(item)
    return files


def write_kol_notes(
    notes_dir: Path,
    author_posts: dict[str, list],
    author_cards: dict[str, list],
    author_files: dict[str, set[str]],
    max_examples: int = 8,
) -> list[str]:
    notes_dir.mkdir(parents=True, exist_ok=True)
    note_paths: list[str] = []
    generated_at = datetime.now(UTC).isoformat()
    for author in sorted(author_posts):
        posts = author_posts[author]
        cards = author_cards.get(author, [])
        symbols = Counter(symbol for post in posts for symbol in post.symbols)
        tags = Counter(tag for post in posts for tag in post.tags)
        files = sorted(author_files.get(author, set()))
        path = notes_dir / f"{slug(author)}.md"
        path.write_text(
            render_kol_note(
                author=author,
                posts=posts,
                cards=cards,
                symbols=symbols,
                tags=tags,
                files=files,
                generated_at=generated_at,
                max_examples=max_examples,
            ),
            encoding="utf-8",
        )
        note_paths.append(str(path))
    return note_paths


def render_kol_note(
    author: str,
    posts: list,
    cards: list,
    symbols: Counter,
    tags: Counter,
    files: list[str],
    generated_at: str,
    max_examples: int,
) -> str:
    lines = [
        "---",
        f"kol: {author}",
        f"generated_at: {generated_at}",
        f"kept_posts: {len(posts)}",
        f"strategy_cards: {len(cards)}",
        "type: kol_research_note",
        "---",
        "",
        f"# {author}",
        "",
        "## Snapshot",
        "",
        f"- Kept trade-related posts: {len(posts)}",
        f"- Strategy cards generated: {len(cards)}",
        f"- Source files: {', '.join(files) if files else 'none'}",
        "",
        "## Top Symbols",
        "",
    ]
    lines.extend(render_counter(symbols))
    lines.extend(["", "## Top Tags", ""])
    lines.extend(render_counter(tags))
    lines.extend(["", "## Strategy Cards", ""])
    if cards:
        for card in cards:
            lines.extend(
                [
                    f"### {card.name}",
                    "",
                    f"- Market: {card.market}",
                    f"- Timeframe: {card.timeframe}",
                    f"- Source posts: {card.source_posts}",
                    f"- Confidence bias: {card.confidence_bias}",
                    f"- Preferred symbols: {', '.join(card.preferred_symbols) if card.preferred_symbols else 'none'}",
                    f"- Entry conditions: {', '.join(card.entry_conditions) if card.entry_conditions else 'none'}",
                    f"- Exit conditions: {', '.join(card.exit_conditions) if card.exit_conditions else 'none'}",
                    f"- Risk notes: {', '.join(card.risk_notes) if card.risk_notes else 'none'}",
                    "",
                ]
            )
    else:
        lines.append("- No strategy cards generated yet.")
    lines.extend(["", "## Representative Posts", ""])
    for post in posts[:max_examples]:
        text = post.text.replace("\n", " ").strip()
        if len(text) > 360:
            text = text[:357] + "..."
        lines.extend(
            [
                f"### {post.created_at.isoformat() if post.created_at else 'unknown_time'}",
                "",
                f"- Symbols: {', '.join(post.symbols) if post.symbols else 'none'}",
                f"- Engagement: likes={post.likes}, reposts={post.reposts}, replies={post.replies}, views={post.views}",
                f"- URL: {post.url or 'none'}",
                "",
                f"> {text}",
                "",
            ]
        )
    lines.extend(
        [
            "## Next Review",
            "",
            "- Check whether generated cards describe a repeatable setup.",
            "- Run `scripts/backtest_kol_cards.py` after enough dated posts are imported.",
            "- Promote only cards with enough samples and stable RR.",
            "",
        ]
    )
    return "\n".join(lines)


def render_counter(counter: Counter) -> list[str]:
    if not counter:
        return ["- none"]
    return [f"- {name}: {count}" for name, count in counter.most_common(10)]


def filter_strategy_cards(cards: list, min_source_posts: int = 5) -> list:
    kept: list = []
    seen_names: set[str] = set()
    for card in sorted(cards, key=lambda item: (-item.source_posts, item.name)):
        if card.name in seen_names:
            continue
        if card.source_posts < min_source_posts:
            continue
        if "manual_review_required" in card.entry_conditions:
            continue
        if not is_reasonable_card_name(card.name):
            continue
        seen_names.add(card.name)
        kept.append(card)
    return kept


def is_reasonable_card_name(name: str) -> bool:
    if len(name) > 48:
        return False
    if any(ch.isspace() for ch in name):
        return False
    if re.search(r"[\u4e00-\u9fff]{6,}", name):
        return False
    if sum(ch.isdigit() for ch in name) > max(4, len(name) // 3):
        return False
    return True


def slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    return cleaned or "unknown"


if __name__ == "__main__":
    main()
