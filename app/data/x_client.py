from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.knowledge.kol_import import RawKOLPost, extract_symbols_from_text, from_legacy_text


class XPost(BaseModel):
    author: str
    text: str
    created_at: str | None = None
    url: str | None = None
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    views: int = 0
    source: str = "x"
    symbols: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class XExportAdapter:
    """Import adapter for X/Twitter export files.

    Supports JSON, CSV and TXT exports. The goal is to bring local exports into the
    KOL pipeline without requiring live X API access.
    """

    def load_posts(self, path: Path, input_format: str = "auto") -> list[XPost]:
        suffix = path.suffix.lower().lstrip(".")
        mode = input_format if input_format != "auto" else suffix
        if mode == "json":
            return self._load_json(path)
        if mode == "csv":
            return self._load_csv(path)
        if mode in {"txt", "md"}:
            return self._load_txt(path)
        return self._load_json(path) if suffix == "json" else self._load_txt(path)

    def to_raw_posts(self, posts: list[XPost]) -> list[RawKOLPost]:
        raw_posts: list[RawKOLPost] = []
        for post in posts:
            raw_posts.append(
                RawKOLPost(
                    author=post.author,
                    text=post.text,
                    created_at=post.created_at,
                    url=post.url,
                    likes=post.likes,
                    reposts=post.reposts,
                    replies=post.replies,
                    views=post.views,
                    symbols=post.symbols or extract_symbols_from_text(post.text),
                    tags=post.tags,
                    source=post.source,
                )
            )
        return raw_posts

    def load_raw_posts(self, path: Path, input_format: str = "auto") -> list[RawKOLPost]:
        return self.to_raw_posts(self.load_posts(path, input_format))

    def _load_json(self, path: Path) -> list[XPost]:
        payload = json.loads(self._read_text(path))
        if isinstance(payload, dict):
            payload = payload.get("posts", payload.get("items", []))
        posts: list[XPost] = []
        for item in payload:
            if isinstance(item, str):
                legacy = from_legacy_text(item)
                posts.append(self._from_raw(legacy))
            elif isinstance(item, dict):
                posts.append(self._from_dict(item, path))
        return posts

    def _load_csv(self, path: Path) -> list[XPost]:
        posts: list[XPost] = []
        payload = self._read_text(path)
        reader = csv.DictReader(io.StringIO(payload))
        for row in reader:
            posts.append(self._from_dict(row, path))
        return posts

    def _load_txt(self, path: Path) -> list[XPost]:
        posts: list[XPost] = []
        for line in self._read_text(path).splitlines():
            text = line.strip()
            if not text:
                continue
            posts.append(self._from_dict({"text": text}))
        return posts

    def _from_dict(self, data: dict, path: Path | None = None) -> XPost:
        text = str(data.get("text", "")).strip()
        author = self._normalize_author(
            self._pick(
                data,
                [
                    "author",
                    "Author",
                    "username",
                    "Username",
                    "user_name",
                    "UserName",
                    "handle",
                    "screen_name",
                    "Screen Name",
                    "screenName",
                ],
                default=None,
            ),
            path,
        )
        created_at = self._pick(data, ["created_at", "date", "timestamp", "time"])
        url = self._pick(data, ["url", "link", "permalink"])
        likes = self._to_int(self._pick(data, ["likes", "like_count", "favorite_count", "favorites"]))
        reposts = self._to_int(self._pick(data, ["reposts", "retweets", "retweet_count", "shares"]))
        replies = self._to_int(self._pick(data, ["replies", "reply_count", "comments"]))
        views = self._to_int(self._pick(data, ["views", "impressions", "view_count"]))
        symbols = self._to_list(self._pick(data, ["symbols", "tickers", "coins"]))
        tags = self._to_list(self._pick(data, ["tags", "labels", "topics"]))
        if not symbols:
            symbols = extract_symbols_from_text(text)
        return XPost(
            author=author,
            text=text,
            created_at=created_at,
            url=url,
            likes=likes,
            reposts=reposts,
            replies=replies,
            views=views,
            source=str(self._pick(data, ["source"], default="x")),
            symbols=symbols,
            tags=tags,
        )

    @staticmethod
    def _normalize_author(value, path: Path | None) -> str:
        text = str(value or "").strip().lstrip("@")
        if text and text.lower() not in {"unknown", "none", "null", "nan"}:
            return text
        if path and path.parent and path.parent.name:
            return path.parent.name.strip().lstrip("@") or "unknown"
        return "unknown"

    @staticmethod
    def _read_text(path: Path) -> str:
        encodings = ("utf-8-sig", "utf-8", "gb18030", "gbk")
        last_error: UnicodeDecodeError | None = None
        for encoding in encodings:
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _from_raw(post: RawKOLPost) -> XPost:
        return XPost(
            author=post.author,
            text=post.text,
            created_at=post.created_at.isoformat() if post.created_at else None,
            url=post.url,
            likes=post.likes,
            reposts=post.reposts,
            replies=post.replies,
            views=post.views,
            source=post.source,
            symbols=post.symbols,
            tags=post.tags,
        )

    @staticmethod
    def _pick(data: dict, keys: list[str], default=None):
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return default

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_list(value) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(value).strip()]
