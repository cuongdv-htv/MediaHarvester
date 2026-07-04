"""UA pool: User-Agent thật + delay ngẫu nhiên (anti-block cho ddgs/generic_scraper)."""

from __future__ import annotations

import asyncio
import random

_USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
]


def random_ua() -> str:
    """Trả về một User-Agent thật ngẫu nhiên."""
    return random.choice(_USER_AGENTS)


async def polite_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
    """Delay ngẫu nhiên giữa các request tới cùng domain (tránh bị chặn)."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))
