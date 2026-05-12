import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.onchainos_export import (
    export_onchainos_signals,
    load_onchainos_signal_payload,
    write_onchainos_signal_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert raw OKX OnchainOS signal-list JSON into the local snapshot format."
    )
    parser.add_argument("input_file", type=Path, help="Raw JSON file exported from onchainos signal list")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/onchainos/signals.snapshot.json"),
        help="Normalized snapshot JSON output path",
    )
    parser.add_argument("--chain", default=None, help="Optional default chain name if the payload omits it")
    parser.add_argument("--min-signal-score", type=float, default=0.0)
    parser.add_argument("--min-wallet-count", type=int, default=1)
    args = parser.parse_args()

    payload = load_onchainos_signal_payload(args.input_file)
    snapshot = export_onchainos_signals(
        payload,
        default_chain=args.chain,
        min_signal_score=args.min_signal_score,
        min_wallet_count=args.min_wallet_count,
    )
    write_onchainos_signal_snapshot(args.output, snapshot)

    summary = {
        "input_file": str(args.input_file),
        "output": str(args.output),
        "signals": len(snapshot.get("signals", [])),
        "meta": snapshot.get("meta", {}),
        "symbols": [item.get("symbol") for item in snapshot.get("signals", [])[:20]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
