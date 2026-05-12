import argparse
import asyncio
import sys

import httpx


async def main_async(proxy: str | None) -> None:
    urls = [
        "https://x.com",
        "https://api.x.com",
        "https://twitter.com",
        "https://api.twitter.com/1.1/guest/activate.json",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5I5zYgH0Q4l4Ks%3D",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(proxy=proxy, timeout=20.0, follow_redirects=True) as client:
        for url in urls[:3]:
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                print({"url": url, "status_code": resp.status_code, "ok": True})
            except Exception as exc:
                print({"url": url, "ok": False, "error": f"{exc.__class__.__name__}: {exc}"})

        try:
            resp = await client.post(urls[3], headers=headers, json={})
            print({"url": urls[3], "status_code": resp.status_code, "ok": True, "body_preview": resp.text[:200]})
        except Exception as exc:
            print({"url": urls[3], "ok": False, "error": f"{exc.__class__.__name__}: {exc}"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether this machine can reach X/Twitter endpoints.")
    parser.add_argument("--proxy", default=None, help="HTTP proxy URL, e.g. http://127.0.0.1:7890")
    args = parser.parse_args()
    asyncio.run(main_async(args.proxy))


if __name__ == "__main__":
    main()
