from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class RawKOLPost(BaseModel):
    author: str
    text: str
    created_at: datetime | None = None
    url: str | None = None
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    views: int = 0
    symbols: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source: str = "x"

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    @model_validator(mode="after")
    def _populate_symbols(self):
        if not self.symbols:
            self.symbols = extract_symbols_from_text(self.text)
        else:
            self.symbols = [normalize_symbol(symbol) for symbol in self.symbols]
        self.tags = [tag.strip() for tag in self.tags if tag and tag.strip()]
        return self


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("-", "").replace("/", "")


def extract_symbols_from_text(text: str) -> list[str]:
    symbols: set[str] = set()
    for token in text.replace(",", " ").replace(".", " ").split():
        cleaned = token.strip().upper()
        if cleaned.endswith("USDT") and 5 <= len(cleaned) <= 20:
            symbols.add(normalize_symbol(cleaned))
        if cleaned.startswith("$") and len(cleaned) > 1:
            symbols.add(normalize_symbol(cleaned[1:]))
    return sorted(symbols)


def from_legacy_text(text: str, author: str = "unknown", source: str = "text") -> RawKOLPost:
    symbols = extract_symbols_from_text(text)
    return RawKOLPost(author=author, text=text, symbols=symbols, source=source)
