from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CRITICAL_RISK_LEVELS = {"CRITICAL", "5", "4"}


def load_onchainos_risk_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def export_onchainos_risks(
    security_payload: Any | None = None,
    advanced_payload: Any | None = None,
    *,
    default_chain: str | None = None,
) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}

    for item in _extract_items(advanced_payload):
        normalized = normalize_advanced_info(item, default_chain=default_chain)
        if not normalized:
            continue
        merged[normalized["symbol"]] = normalized

    for item in _extract_items(security_payload):
        normalized = normalize_security_scan(item, default_chain=default_chain)
        if not normalized:
            continue
        current = merged.get(normalized["symbol"], {"symbol": normalized["symbol"]})
        current.update({k: v for k, v in normalized.items() if v not in (None, "", [])})
        current["risk_tags"] = sorted(set((current.get("risk_tags") or []) + (normalized.get("risk_tags") or [])))
        current["honeypot"] = bool(current.get("honeypot") or normalized.get("honeypot"))
        if normalized.get("is_safe_buy") is False:
            current["is_safe_buy"] = False
        merged[normalized["symbol"]] = current

    risks = sorted(merged.values(), key=_risk_sort_key, reverse=True)
    return {
        "source": "okx_onchainos",
        "kind": "risk_snapshot",
        "risks": risks,
        "meta": {
            "count": len(risks),
            "default_chain": default_chain,
        },
    }


def write_onchainos_risk_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_security_scan(item: dict[str, Any], default_chain: str | None = None) -> dict[str, Any] | None:
    token = item.get("token") if isinstance(item.get("token"), dict) else {}
    symbol = str(item.get("symbol") or token.get("symbol") or item.get("tokenSymbol") or "").strip()
    if not symbol:
        return None
    risk_level = str(item.get("riskLevel") or item.get("risk_level") or "unknown")
    labels = item.get("labels") or item.get("riskLabels") or item.get("triggeredLabels") or []
    if isinstance(labels, str):
        labels = [part.strip() for part in labels.split(",") if part.strip()]
    normalized_tags = [str(label).strip() for label in labels if str(label).strip()]
    honeypot = any("honeypot" in label.lower() for label in normalized_tags)
    action = str(item.get("action") or "").lower()
    is_safe_buy = not (honeypot or risk_level.upper() == "CRITICAL" or action == "block")
    return {
        "symbol": _normalize_symbol(symbol),
        "token_symbol": _normalize_symbol(symbol),
        "token_address": str(item.get("tokenAddress") or token.get("tokenAddress") or "").strip().lower(),
        "chain": str(item.get("chain") or item.get("chainName") or default_chain or "").strip().lower(),
        "risk_level": risk_level,
        "risk_tags": normalized_tags,
        "honeypot": honeypot,
        "is_safe_buy": is_safe_buy,
    }


def normalize_advanced_info(item: dict[str, Any], default_chain: str | None = None) -> dict[str, Any] | None:
    symbol = str(item.get("symbol") or item.get("tokenSymbol") or item.get("token_symbol") or "").strip()
    if not symbol:
        return None
    tags = item.get("tokenTags") or item.get("risk_tags") or []
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",") if part.strip()]
    normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    honeypot = any("honeypot" in tag.lower() for tag in normalized_tags)
    risk_level = str(item.get("riskControlLevel") or item.get("risk_level") or "unknown")
    return {
        "symbol": _normalize_symbol(symbol),
        "token_symbol": _normalize_symbol(symbol),
        "token_address": str(item.get("tokenAddress") or item.get("tokenContractAddress") or "").strip().lower(),
        "chain": str(item.get("chain") or item.get("chainName") or default_chain or "").strip().lower(),
        "risk_level": risk_level,
        "risk_tags": normalized_tags,
        "honeypot": honeypot,
        "top10_holder_percent": _optional_float(item.get("top10HoldPercent") or item.get("top10_holder_percent")),
        "dev_holding_percent": _optional_float(item.get("devHoldingPercent") or item.get("dev_holding_percent")),
        "bundle_holding_percent": _optional_float(
            item.get("bundleHoldingPercent") or item.get("bundle_holding_percent")
        ),
        "suspicious_holding_percent": _optional_float(
            item.get("suspiciousHoldingPercent") or item.get("suspicious_holding_percent")
        ),
        "liquidity_usd": _optional_float(item.get("liquidityUsd") or item.get("liquidity_usd")),
    }


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("risks", "signals", "items", "data", "result", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for nested_key in ("items", "data", "rows", "list"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return [payload] if payload else []


def _normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper().lstrip("$")
    for quote in ("USDT", "USDC", "USD", "PERP"):
        if cleaned.endswith(quote) and len(cleaned) > len(quote):
            return cleaned[: -len(quote)]
    return cleaned


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _risk_sort_key(item: dict[str, Any]) -> tuple[int, int, float]:
    risk_level = str(item.get("risk_level") or "unknown").upper()
    hard = 1 if item.get("honeypot") else 0
    critical = 1 if risk_level in CRITICAL_RISK_LEVELS else 0
    concentration = float(item.get("top10_holder_percent") or 0)
    return hard, critical, concentration
