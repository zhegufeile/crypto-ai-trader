from __future__ import annotations

import json
from pathlib import Path
from typing import Any


WALLET_TYPE_MAP = {
    "1": "smart_money",
    "2": "kol",
    "3": "whale",
    "smart money": "smart_money",
    "smart_money": "smart_money",
    "kol": "kol",
    "influencer": "kol",
    "whale": "whale",
}


def load_onchainos_signal_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def export_onchainos_signals(
    payload: Any,
    *,
    default_chain: str | None = None,
    min_signal_score: float = 0.0,
    min_wallet_count: int = 1,
) -> dict[str, Any]:
    items = _extract_items(payload)
    signals = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = normalize_onchainos_signal(item, default_chain=default_chain)
        if not normalized:
            continue
        if normalized["signal_score"] < min_signal_score:
            continue
        if normalized["wallet_count"] < min_wallet_count:
            continue
        signals.append(normalized)

    signals.sort(
        key=lambda item: (
            item.get("signal_score", 0),
            item.get("wallet_count", 0),
            item.get("buy_amount_usd", 0),
            item.get("timestamp", ""),
        ),
        reverse=True,
    )
    return {
        "source": "okx_onchainos",
        "kind": "signal_snapshot",
        "signals": signals,
        "meta": {
            "count": len(signals),
            "default_chain": default_chain,
            "min_signal_score": min_signal_score,
            "min_wallet_count": min_wallet_count,
        },
    }


def normalize_onchainos_signal(item: dict[str, Any], default_chain: str | None = None) -> dict[str, Any] | None:
    token = item.get("token") if isinstance(item.get("token"), dict) else {}
    symbol = str(
        token.get("symbol")
        or item.get("symbol")
        or item.get("token_symbol")
        or item.get("tokenSymbol")
        or ""
    ).strip()
    if not symbol:
        return None

    wallet_types = _normalize_wallet_types(item.get("walletType") or item.get("wallet_types") or item.get("wallet_type"))
    wallet_count = _to_int(item.get("triggerWalletCount") or item.get("wallet_count") or item.get("walletCount") or 0)
    buy_amount_usd = _to_float(item.get("amountUsd") or item.get("buy_amount_usd") or item.get("buyAmountUsd") or 0)
    sold_ratio_percent = _optional_float(item.get("soldRatioPercent") or item.get("sold_ratio_percent"))
    top10_holder_percent = _optional_float(token.get("top10HolderPercent") or item.get("top10HolderPercent"))
    signal_score = _compute_signal_score(
        wallet_types=wallet_types,
        wallet_count=wallet_count,
        buy_amount_usd=buy_amount_usd,
        sold_ratio_percent=sold_ratio_percent,
        top10_holder_percent=top10_holder_percent,
    )
    chain = str(item.get("chainName") or item.get("chain") or default_chain or "").strip().lower()

    return {
        "symbol": _normalize_symbol(symbol),
        "token_symbol": _normalize_symbol(symbol),
        "token_name": str(token.get("name") or item.get("tokenName") or "").strip(),
        "token_address": str(token.get("tokenAddress") or item.get("tokenAddress") or "").strip().lower(),
        "chain": chain,
        "chain_index": str(item.get("chainIndex") or ""),
        "timestamp": str(item.get("timestamp") or item.get("requestTime") or ""),
        "signal_score": signal_score,
        "wallet_count": wallet_count,
        "buy_amount_usd": round(buy_amount_usd, 2),
        "sold_ratio_percent": sold_ratio_percent,
        "wallet_types": wallet_types,
        "trigger_wallet_address": str(item.get("triggerWalletAddress") or "").strip(),
        "price": _optional_float(item.get("price")),
        "market_cap_usd": _optional_float(token.get("marketCapUsd") or item.get("marketCapUsd")),
        "holders": _to_int(token.get("holders") or item.get("holders") or 0),
        "top10_holder_percent": top10_holder_percent,
        "cursor": item.get("cursor"),
    }


def write_onchainos_signal_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("signals", "items", "data", "result", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested_key in ("items", "data", "rows", "list"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested
    return []


def _normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper().lstrip("$")
    for quote in ("USDT", "USDC", "USD", "PERP"):
        if cleaned.endswith(quote) and len(cleaned) > len(quote):
            return cleaned[: -len(quote)]
    return cleaned


def _normalize_wallet_types(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    parts: list[str]
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
    else:
        parts = [part.strip() for part in str(value).split(",") if part.strip()]
    normalized: list[str] = []
    for part in parts:
        mapped = WALLET_TYPE_MAP.get(part.lower(), WALLET_TYPE_MAP.get(part, part.lower()))
        if mapped not in normalized:
            normalized.append(mapped)
    return normalized


def _compute_signal_score(
    *,
    wallet_types: list[str],
    wallet_count: int,
    buy_amount_usd: float,
    sold_ratio_percent: float | None,
    top10_holder_percent: float | None,
) -> float:
    score = 0.3
    if "smart_money" in wallet_types:
        score += 0.12
    if "kol" in wallet_types:
        score += 0.08
    if "whale" in wallet_types:
        score += 0.08

    score += min(wallet_count, 5) / 5 * 0.2

    if buy_amount_usd >= 250_000:
        score += 0.18
    elif buy_amount_usd >= 100_000:
        score += 0.14
    elif buy_amount_usd >= 50_000:
        score += 0.10
    elif buy_amount_usd >= 10_000:
        score += 0.06

    if sold_ratio_percent is not None:
        if sold_ratio_percent <= 20:
            score += 0.15
        elif sold_ratio_percent <= 35:
            score += 0.10
        elif sold_ratio_percent >= 70:
            score -= 0.14
        elif sold_ratio_percent >= 50:
            score -= 0.08

    if top10_holder_percent is not None:
        if top10_holder_percent >= 85:
            score -= 0.08
        elif top10_holder_percent >= 70:
            score -= 0.04

    return round(max(0.0, min(score, 1.0)), 3)


def _to_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
