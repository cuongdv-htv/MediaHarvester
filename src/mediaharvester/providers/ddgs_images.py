"""Provider DuckDuckGo Images — không cần API key.

Anti-block theo spec: UA pool thật, delay ngẫu nhiên 1–3s trước mỗi download,
fallback curl_cffi (impersonate chrome) khi bị 403/blocked.
License luôn "unknown" — user tự kiểm tra bản quyền ảnh web.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx
from loguru import logger

from mediaharvester.core.downloader import download_with_retry
from mediaharvester.core.organizer import build_filename, ext_from_url
from mediaharvester.providers.base import (
    MediaType,
    Provider,
    SearchResult,
    register_provider,
)
from mediaharvester.utils.ua_pool import polite_delay, random_ua


def _curl_cffi_fetch(url: str, dest: Path, ua: str) -> Path:
    """Fallback chống 403: tải bằng curl_cffi impersonate Chrome (blocking)."""
    from curl_cffi import requests as curl_requests

    resp = curl_requests.get(
        url, impersonate="chrome", timeout=60, headers={"User-Agent": ua}
    )
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


@register_provider
class DdgsImagesProvider(Provider):
    """Nguồn ảnh qua DuckDuckGo Images — đa dạng nhưng license không rõ ràng."""

    name = "ddgs"
    supported_types = {MediaType.IMAGE}
    requires_api_key = False

    def __init__(self, api_key: str = "", client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30)

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Tìm ảnh qua DDGS (thư viện sync → chạy trong thread)."""
        if media_type != MediaType.IMAGE:
            return []
        rows = await asyncio.to_thread(self._search_sync, query, per_page * page)
        # DDGS không phân trang chuẩn — lấy dư rồi cắt theo page
        rows = rows[(page - 1) * per_page : page * per_page]
        results: list[SearchResult] = []
        for row in rows:
            if not row.get("image"):
                continue
            results.append(
                SearchResult(
                    provider=self.name,
                    media_type=MediaType.IMAGE,
                    title=row.get("title") or "ddgs-image",
                    thumbnail_url=row.get("thumbnail", ""),
                    download_url=row["image"],
                    source_page_url=row.get("url", ""),
                    license="unknown (ảnh web — tự kiểm tra bản quyền)",
                    author=row.get("source"),
                    width=row.get("width"),
                    height=row.get("height"),
                    extra={},
                )
            )
        logger.debug("DDGS: {} kết quả cho '{}'", len(results), query)
        return results

    def _search_sync(self, query: str, max_results: int) -> list[dict]:
        # Package `duckduckgo_search` đã đổi tên thành `ddgs` (cùng class DDGS)
        from ddgs import DDGS

        with DDGS() as ddgs:
            return list(ddgs.images(query, max_results=max_results, safesearch="moderate"))

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải ảnh web: delay lịch sự + UA thật; 403 → fallback curl_cffi."""
        url = result.download_url
        ua = random_ua()
        dest = dest_dir / build_filename(self.name, result.title, ext_from_url(url, ".jpg"), url)
        await polite_delay(1.0, 3.0)
        try:
            return await download_with_retry(
                self._client, url, dest, progress_cb, headers={"User-Agent": ua}
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (403, 429):
                raise
            logger.info("DDGS bị {} — fallback curl_cffi: {}", exc.response.status_code, url)
            path = await asyncio.to_thread(_curl_cffi_fetch, url, dest, ua)
            progress_cb(path.stat().st_size, path.stat().st_size)
            return path

    async def health_check(self) -> bool:
        """DDGS hoạt động nếu search thử trả về được (không cần key)."""
        try:
            rows = await asyncio.to_thread(self._search_sync, "test", 1)
            return bool(rows)
        except Exception as exc:
            logger.warning("DDGS health-check lỗi: {}", exc)
            return False
