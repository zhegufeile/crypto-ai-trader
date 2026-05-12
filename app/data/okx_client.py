from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class OnchainSignalAdapter(Protocol):
    async def get_symbol_signal_map(self, symbols: list[str]) -> dict[str, dict[str, Any]]: ...


class OKXClient:
    """Onchain signal adapter for OKX OnchainOS data.

    This client is intentionally lightweight: Binance remains the primary market source,
    while OKX/OnchainOS acts as an optional booster for smart-money/KOL/whale flow.
    """

    def __init__(
        self,
        signal_snapshot_file: str | Path | None = None,
        risk_snapshot_file: str | Path | None = None,
        adapter: OnchainSignalAdapter | None = None,
    ) -> None:
        self.signal_snapshot_file = Path(signal_snapshot_file) if signal_snapshot_file else None
        self.risk_snapshot_file = Path(risk_snapshot_file) if risk_snapshot_file else None
        self.adapter = adapter

    async def get_symbol_signal_map(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if self.adapter is not None:
            return await self.adapter.get_symbol_signal_map(symbols)
        if self.signal_snapshot_file and self.signal_snapshot_file.exists():
            return self._load_signal_snapshot(symbols)
        return {}

    def _load_signal_snapshot(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        payload = json.loads(self.signal_snapshot_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            items = payload.get("signals", payload.get("items", []))
        else:
            items = payload
        requested = {self._normalize_symbol(symbol) for symbol in symbols}
        signal_map: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_symbol(
                str(item.get("symbol") or item.get("token_symbol") or item.get("token") or "")
            )
            if not normalized or normalized not in requested:
                continue
            signal_map[normalized] = self._normalize_signal(item)
        return signal_map

    async def get_symbol_risk_map(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if self.risk_snapshot_file and self.risk_snapshot_file.exists():
            return self._load_risk_snapshot(symbols)
        return {}

    def _load_risk_snapshot(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        payload = json.loads(self.risk_snapshot_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            items = payload.get("risks", payload.get("items", []))
        else:
            items = payload
        requested = {self._normalize_symbol(symbol) for symbol in symbols}
        risk_map: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_symbol(
                str(item.get("symbol") or item.get("token_symbol") or item.get("token") or "")
            )
            if not normalized or normalized not in requested:
                continue
            risk_map[normalized] = self._normalize_risk(item)
        return risk_map

    @staticmethod
    def _normalize_signal(item: dict[str, Any]) -> dict[str, Any]:
        wallet_types = item.get("wallet_types") or item.get("walletType") or item.get("wallet_type") or []
        if isinstance(wallet_types, str):
            wallet_types = [part.strip() for part in wallet_types.split(",") if part.strip()]
        return {
            "symbol": OKXClient._normalize_symbol(
                str(item.get("symbol") or item.get("token_symbol") or item.get("token") or "")
            ),
            "signal_score": OKXClient._to_float(
                item.get("signal_score") or item.get("signalScore") or item.get("score") or 0
            ),
            "wallet_count": int(item.get("wallet_count") or item.get("walletCount") or 0),
            "buy_amount_usd": OKXClient._to_float(
                item.get("buy_amount_usd") or item.get("buyAmountUsd") or item.get("amountUsd") or 0
            ),
            "sold_ratio_percent": OKXClient._optional_float(
                item.get("sold_ratio_percent") or item.get("soldRatioPercent")
            ),
            "wallet_types": [str(part).strip() for part in wallet_types if str(part).strip()],
            "chain": str(item.get("chain") or item.get("chainName") or ""),
        }

    @staticmethod
    def _normalize_risk(item: dict[str, Any]) -> dict[str, Any]:
        tags = item.get("risk_tags") or item.get("tokenTags") or item.get("tags") or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(",") if part.strip()]
        normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        risk_level = str(item.get("risk_level") or item.get("riskLevel") or item.get("riskControlLevel") or "unknown")
        return {
            "symbol": OKXClient._normalize_symbol(
                str(item.get("symbol") or item.get("token_symbol") or item.get("token") or "")
            ),
            "risk_level": risk_level,
            "risk_tags": normalized_tags,
            "honeypot": bool(item.get("honeypot") or "honeypot" in {tag.lower() for tag in normalized_tags}),
            "is_safe_buy": item.get("is_safe_buy"),
            "top10_holder_percent": OKXClient._optional_float(
                item.get("top10_holder_percent") or item.get("top10HolderPercent")
            ),
            "dev_holding_percent": OKXClient._optional_float(
                item.get("dev_holding_percent") or item.get("devHoldingPercent")
            ),
            "bundle_holding_percent": OKXClient._optional_float(
                item.get("bundle_holding_percent") or item.get("bundleHoldingPercent")
            ),
            "suspicious_holding_percent": OKXClient._optional_float(
                item.get("suspicious_holding_percent") or item.get("suspiciousHoldingPercent")
            ),
            "liquidity_usd": OKXClient._optional_float(item.get("liquidity_usd") or item.get("liquidityUsd")),
            "chain": str(item.get("chain") or item.get("chainName") or ""),
        }

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        cleaned = symbol.strip().upper().lstrip("$")
        for quote in ("USDT", "USDC", "USD", "PERP"):
            if cleaned.endswith(quote) and len(cleaned) > len(quote):
                return cleaned[: -len(quote)]
        return cleaned

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value in (None, "", "null"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
