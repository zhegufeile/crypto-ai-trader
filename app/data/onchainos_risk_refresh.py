from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.data.onchainos_cli import OnchainOSCLI
from app.data.onchainos_risk_export import export_onchainos_risks, write_onchainos_risk_snapshot


CHAIN_INDEX_MAP = {
    "solana": "501",
    "ethereum": "1",
    "base": "8453",
    "bsc": "56",
    "arbitrum": "42161",
    "polygon": "137",
}


@dataclass(slots=True)
class RiskRefreshTarget:
    symbol: str
    address: str
    chain: str
    chain_index: str


def load_signal_targets(path: Path) -> list[RiskRefreshTarget]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    items = payload.get("signals", []) if isinstance(payload, dict) else payload
    targets: list[RiskRefreshTarget] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or item.get("token_symbol") or "").strip().upper()
        address = str(item.get("token_address") or item.get("tokenAddress") or "").strip().lower()
        chain = str(item.get("chain") or "").strip().lower()
        chain_index = str(item.get("chain_index") or item.get("chainIndex") or CHAIN_INDEX_MAP.get(chain) or "").strip()
        if not symbol or not address or not chain or not chain_index:
            continue
        key = (chain_index, address)
        if key in seen:
            continue
        seen.add(key)
        targets.append(RiskRefreshTarget(symbol=symbol, address=address, chain=chain, chain_index=chain_index))
    return targets


def refresh_onchainos_risks(
    *,
    targets: list[RiskRefreshTarget],
    cli: OnchainOSCLI,
    output_path: Path,
    security_raw_output: Path | None = None,
    advanced_raw_output: Path | None = None,
) -> dict[str, Any]:
    security_payload = cli.security_token_scan(tokens=[(target.chain_index, target.address) for target in targets])
    advanced_items: list[Any] = []
    for target in targets:
        advanced_items.append(cli.token_advanced_info(address=target.address, chain=target.chain))

    normalized_advanced = {"data": [_unwrap_single_result(item) for item in advanced_items if _unwrap_single_result(item)]}
    snapshot = export_onchainos_risks(security_payload, normalized_advanced)
    write_onchainos_risk_snapshot(output_path, snapshot)

    if security_raw_output:
        security_raw_output.parent.mkdir(parents=True, exist_ok=True)
        security_raw_output.write_text(json.dumps(security_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if advanced_raw_output:
        advanced_raw_output.parent.mkdir(parents=True, exist_ok=True)
        advanced_raw_output.write_text(json.dumps(normalized_advanced, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "targets": [target.symbol for target in targets],
        "security_count": len(_extract_items(security_payload)),
        "advanced_count": len(normalized_advanced["data"]),
        "output": str(output_path),
        "blocked_symbols": [
            item.get("symbol")
            for item in snapshot.get("risks", [])
            if item.get("honeypot") or str(item.get("risk_level", "")).upper() == "CRITICAL"
        ],
    }


def _unwrap_single_result(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        for key in ("data", "result", "item"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                return nested
            if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                return nested[0]
        return payload if payload else None
    return None


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "result", "items", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []
