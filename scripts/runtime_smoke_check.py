import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    endpoints = [
        ("/health", "health"),
        ("/health/ready", "ready"),
        ("/strategy-cards", "strategy_cards"),
        ("/strategy-cards/leaderboard?limit=5", "leaderboard"),
        ("/diagnostics/candidates?limit=5", "diagnostics"),
        ("/positions?include_closed=true", "positions"),
        ("/positions/journal?limit=10", "journal"),
    ]

    summary: dict[str, dict] = {}
    overall_ok = True

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        for path, name in endpoints:
            try:
                response = client.get(path)
                ok = response.status_code == 200
                overall_ok = overall_ok and ok
                payload_preview = _preview_payload(response)
                summary[name] = {
                    "ok": ok,
                    "status_code": response.status_code,
                    "path": path,
                    "preview": payload_preview,
                }
            except Exception as exc:  # pragma: no cover
                overall_ok = False
                summary[name] = {
                    "ok": False,
                    "status_code": None,
                    "path": path,
                    "preview": str(exc),
                }

    result = {
        "status": "pass" if overall_ok else "fail",
        "base_url": base_url,
        "checks": summary,
    }
    print(json.dumps(result, indent=2, ensure_ascii=True))
    if not overall_ok:
        raise SystemExit(1)


def _preview_payload(response: httpx.Response):
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return response.text[:120]
    payload = response.json()
    if isinstance(payload, list):
        return {"type": "list", "count": len(payload)}
    if isinstance(payload, dict):
        return {"type": "dict", "keys": sorted(payload.keys())[:12]}
    return str(type(payload).__name__)


if __name__ == "__main__":
    main()
