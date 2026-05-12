import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.onchainos_risk_export import (
    export_onchainos_risks,
    load_onchainos_risk_payload,
    write_onchainos_risk_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert raw OKX OnchainOS token-scan and advanced-info JSON into the local risk snapshot format."
    )
    parser.add_argument("--security-input", type=Path, default=None, help="Raw JSON from onchainos security token-scan")
    parser.add_argument("--advanced-input", type=Path, default=None, help="Raw JSON from onchainos token advanced-info")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/onchainos/risks.snapshot.json"),
        help="Normalized risk snapshot JSON output path",
    )
    parser.add_argument("--chain", default=None, help="Optional default chain name if the payload omits it")
    args = parser.parse_args()

    if not args.security_input and not args.advanced_input:
        raise SystemExit("Provide at least one of --security-input or --advanced-input.")

    security_payload = load_onchainos_risk_payload(args.security_input) if args.security_input else None
    advanced_payload = load_onchainos_risk_payload(args.advanced_input) if args.advanced_input else None
    snapshot = export_onchainos_risks(security_payload, advanced_payload, default_chain=args.chain)
    write_onchainos_risk_snapshot(args.output, snapshot)

    summary = {
        "security_input": str(args.security_input) if args.security_input else None,
        "advanced_input": str(args.advanced_input) if args.advanced_input else None,
        "output": str(args.output),
        "risks": len(snapshot.get("risks", [])),
        "blocked_symbols": [
            item.get("symbol")
            for item in snapshot.get("risks", [])
            if item.get("honeypot") or str(item.get("risk_level", "")).upper() == "CRITICAL"
        ][:20],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
