import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.twikit_export import load_browser_cookie_export


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Twikit cookies.json from browser cookies or manual tokens.")
    parser.add_argument("--browser-export", type=Path, default=None, help="Browser cookie export JSON file.")
    parser.add_argument("--auth-token", default=None, help="X auth_token cookie value.")
    parser.add_argument("--ct0", default=None, help="X ct0 cookie value.")
    parser.add_argument("--output", type=Path, default=Path("data/twikit/cookies.json"))
    args = parser.parse_args()

    cookies: dict[str, str] = {}
    if args.browser_export:
        cookies.update(load_browser_cookie_export(args.browser_export))
    if args.auth_token:
        cookies["auth_token"] = args.auth_token
    if args.ct0:
        cookies["ct0"] = args.ct0

    if "auth_token" not in cookies or "ct0" not in cookies:
        raise SystemExit("Need both auth_token and ct0. Provide --browser-export or pass both --auth-token and --ct0.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"output": str(args.output), "cookie_keys": sorted(cookies.keys())})


if __name__ == "__main__":
    main()
