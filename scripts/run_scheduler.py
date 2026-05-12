import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.scheduler import run_scan_once
from app.storage.db import init_db


async def main() -> None:
    init_db()
    result = await run_scan_once()
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
