from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.knowledge.kol_import import extract_symbols_from_text


def tweet_to_export_record(tweet: Any, screen_name: str) -> dict[str, Any]:
    text = _pick_attr(tweet, ["full_text", "text"], "")
    created_at = _stringify_datetime(_pick_attr(tweet, ["created_at", "created_at_datetime"], None))
    url = _build_tweet_url(screen_name, _pick_attr(tweet, ["id", "id_str"], None))
    likes = _to_int(_pick_attr(tweet, ["favorite_count", "like_count"], 0))
    reposts = _to_int(_pick_attr(tweet, ["retweet_count", "retweets_count"], 0))
    replies = _to_int(_pick_attr(tweet, ["reply_count"], 0))
    views = _to_int(_pick_attr(tweet, ["view_count", "views_count"], 0))
    symbols = extract_symbols_from_text(text)

    return {
        "id": str(_pick_attr(tweet, ["id", "id_str"], "")),
        "author": screen_name,
        "text": text,
        "created_at": created_at,
        "url": url,
        "likes": likes,
        "reposts": reposts,
        "replies": replies,
        "views": views,
        "symbols": symbols,
        "tags": [],
        "source": "twikit",
    }


def load_existing_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return list(payload.get("posts", []))
    return []


def save_json_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def save_csv_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "author",
        "text",
        "created_at",
        "url",
        "likes",
        "reposts",
        "replies",
        "views",
        "symbols",
        "tags",
        "source",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = record.copy()
            row["symbols"] = ",".join(record.get("symbols", []))
            row["tags"] = ",".join(record.get("tags", []))
            writer.writerow(row)


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        fingerprint = record.get("id") or f"{record.get('author')}|{record.get('created_at')}|{record.get('text')}"
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(record)
    return unique


def merge_records(existing: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = dedupe_records(existing + fresh)
    return sorted(merged, key=lambda item: item.get("created_at") or "", reverse=True)


def load_browser_cookie_export(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "auth_token" in payload or "ct0" in payload:
            return {
                key: value
                for key, value in payload.items()
                if key in {"auth_token", "ct0", "kdt", "twid", "lang", "guest_id", "guest_id_ads", "guest_id_marketing"}
            }
        if "cookies" in payload and isinstance(payload["cookies"], list):
            payload = payload["cookies"]

    cookies: dict[str, str] = {}
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            domain = str(item.get("domain", ""))
            if not name or value in (None, ""):
                continue
            if "x.com" in domain or "twitter.com" in domain or domain in {"", None}:
                cookies[str(name)] = str(value)

    return {
        key: value
        for key, value in cookies.items()
        if key in {"auth_token", "ct0", "kdt", "twid", "lang", "guest_id", "guest_id_ads", "guest_id_marketing"}
    }


def _pick_attr(obj: Any, names: list[str], default: Any) -> Any:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _build_tweet_url(screen_name: str, tweet_id: Any) -> str | None:
    if not tweet_id:
        return None
    return f"https://x.com/{screen_name}/status/{tweet_id}"


def _stringify_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
