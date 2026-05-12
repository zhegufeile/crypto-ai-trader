import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.onchainos_cli import OnchainOSCLI, OnchainOSCLIError
from app.data.onchainos_risk_refresh import load_signal_targets, refresh_onchainos_risks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh local onchain risk snapshot from OKX OnchainOS CLI using tracked token addresses."
    )
    parser.add_argument(
        "--signals-input",
        type=Path,
        default=Path("data/onchainos/signals.snapshot.json"),
        help="Signal snapshot with token_address and chain metadata",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/onchainos/risks.snapshot.json"),
        help="Risk snapshot output path",
    )
    parser.add_argument(
        "--security-raw-output",
        type=Path,
        default=Path("data/onchainos/token_scan.raw.json"),
        help="Optional raw token-scan output path",
    )
    parser.add_argument(
        "--advanced-raw-output",
        type=Path,
        default=Path("data/onchainos/advanced_info.raw.json"),
        help="Optional raw advanced-info output path",
    )
    parser.add_argument("--onchainos-path", default=None, help="Optional explicit onchainos executable path")
    parser.add_argument("--proxy", default=None, help="Optional HTTP/HTTPS proxy URL for onchainos CLI")
    args = parser.parse_args()

    if not args.signals_input.exists():
        raise SystemExit(f"signals snapshot not found: {args.signals_input}")

    targets = load_signal_targets(args.signals_input)
    if not targets:
        raise SystemExit("no valid signal targets found in the signal snapshot")

    cli = OnchainOSCLI(args.onchainos_path, proxy_url=args.proxy)
    try:
        summary = refresh_onchainos_risks(
            targets=targets,
            cli=cli,
            output_path=args.output,
            security_raw_output=args.security_raw_output,
            advanced_raw_output=args.advanced_raw_output,
        )
    except OnchainOSCLIError as exc:
        raise SystemExit(
            "failed to refresh onchain risk snapshot from onchainos CLI. "
            f"details: {exc}"
        ) from exc

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
