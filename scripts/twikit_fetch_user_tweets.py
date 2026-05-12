import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.data.twikit_export import (
    dedupe_records,
    load_existing_records,
    merge_records,
    save_csv_records,
    save_json_records,
    tweet_to_export_record,
)


async def fetch_user_tweets(args) -> None:
    try:
        from twikit import Client
    except ImportError as exc:
        raise SystemExit("twikit is not installed. Run pip install -r requirements.txt first.") from exc

    proxy = args.proxy or os.getenv("X_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    client = Client(args.locale, proxy=proxy)
    cookies_file = str(args.cookies_file)
    if args.cookies_file.exists():
        client.load_cookies(cookies_file)
    else:
        username = args.username or os.getenv("X_USERNAME")
        email = args.email or os.getenv("X_EMAIL")
        password = args.password or os.getenv("X_PASSWORD")
        totp_secret = args.totp_secret or os.getenv("X_TOTP_SECRET")
        if not username or not password:
            raise SystemExit("Missing X credentials. Provide --username/--password or X_USERNAME/X_PASSWORD.")
        try:
            await client.login(
                auth_info_1=username,
                auth_info_2=email,
                password=password,
                totp_secret=totp_secret,
                cookies_file=cookies_file,
            )
        except Exception as exc:
            raise SystemExit(_format_error(exc, proxy, during="login")) from exc

    try:
        user = await client.get_user_by_screen_name(args.screen_name)
        result = await user.get_tweets(args.tweet_type, count=args.page_size)
    except Exception as exc:
        raise SystemExit(_format_error(exc, proxy, during="timeline fetch")) from exc

    existing = load_existing_records(args.output)
    existing_ids = {str(item.get("id", "")) for item in existing if item.get("id")}
    fresh_records: list[dict] = []
    consecutive_existing = 0

    while result:
        page_records = []
        for tweet in result:
            record = tweet_to_export_record(tweet, args.screen_name)
            tweet_id = str(record.get("id", ""))
            if tweet_id and tweet_id in existing_ids:
                consecutive_existing += 1
                if args.resume_stop_streak and consecutive_existing >= args.resume_stop_streak:
                    result = None
                    break
                continue
            consecutive_existing = 0
            if tweet_id:
                existing_ids.add(tweet_id)
            page_records.append(record)
            fresh_records.append(record)
            if args.max_tweets and len(fresh_records) >= args.max_tweets:
                result = None
                break

        if page_records and args.flush_every and len(fresh_records) % args.flush_every == 0:
            merged = merge_records(existing, fresh_records)
            save_json_records(args.output, merged)
            if args.csv_output:
                save_csv_records(args.csv_output, merged)

        if result is None or not hasattr(result, "next"):
            break
        try:
            result = await result.next()
        except Exception as exc:
            raise SystemExit(_format_error(exc, proxy, during="pagination")) from exc

    merged = merge_records(existing, fresh_records)
    merged = dedupe_records(merged)
    save_json_records(args.output, merged)
    if args.csv_output:
        save_csv_records(args.csv_output, merged)

    print(
        {
            "screen_name": args.screen_name,
            "existing_records": len(existing),
            "new_records": len(fresh_records),
            "total_records": len(merged),
            "output": str(args.output),
            "csv_output": str(args.csv_output) if args.csv_output else None,
            "cookies_file": str(args.cookies_file),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch user tweets with Twikit and export pipeline-ready JSON.")
    parser.add_argument("screen_name")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--csv-output", type=Path, default=None)
    parser.add_argument("--cookies-file", type=Path, default=Path("data/twikit/cookies.json"))
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--tweet-type", choices=["Tweets", "Replies", "Media", "Likes"], default="Tweets")
    parser.add_argument("--page-size", type=int, default=40)
    parser.add_argument("--max-tweets", type=int, default=0)
    parser.add_argument("--flush-every", type=int, default=200)
    parser.add_argument("--resume-stop-streak", type=int, default=200)
    parser.add_argument("--username", default=None)
    parser.add_argument("--email", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--totp-secret", default=None)
    parser.add_argument("--proxy", default=None, help="HTTP proxy URL, e.g. http://127.0.0.1:7890")
    return parser


def normalize_args(args):
    if args.output is None:
        args.output = Path("data") / args.screen_name / "posts.twikit.json"
    if args.csv_output is None:
        args.csv_output = Path("data") / args.screen_name / "posts.twikit.csv"
    args.cookies_file.parent.mkdir(parents=True, exist_ok=True)
    return args


def main() -> None:
    parser = build_parser()
    args = normalize_args(parser.parse_args())
    asyncio.run(fetch_user_tweets(args))


def _format_error(exc: Exception, proxy: str | None, during: str) -> str:
    details = [
        f"Twikit failed during {during}.",
        f"Exception: {exc.__class__.__name__}: {exc}",
    ]
    if isinstance(exc, httpx.HTTPError):
        details.append("This looks like a network/proxy/TLS level failure before Twitter login completed.")
    if proxy:
        details.append(f"Proxy in use: {proxy}")
        details.append("If your local proxy is Clash/V2Ray/Surge, prefer an http:// proxy URL instead of https://.")
    else:
        details.append("No proxy configured. If X is blocked on your network, rerun with --proxy http://127.0.0.1:PORT.")
    details.append("You can also set X_PROXY, HTTP_PROXY or HTTPS_PROXY before running the script.")
    return "\n".join(details)


if __name__ == "__main__":
    main()
