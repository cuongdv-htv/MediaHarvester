"""Provider Openverse: ảnh Creative Commons (https://api.openverse.org) — không cần key."""

from __future__ import annotations

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

_BASE = "https://api.openverse.org/v1/images/"
_UA = {"User-Agent": "MediaHarvester/0.1 (https://github.com/cuongdv-htv/MediaHarvester)"}


def _license_text(row: dict) -> str:
    """'by' + '4.0' → 'CC BY 4.0'; 'cc0' → 'CC0'."""
    lic = (row.get("license") or "unknown").lower()
    if lic == "cc0":
        return "CC0"
    version = row.get("license_version") or ""
    return f"CC {lic.upper()} {version}".strip()


@register_provider
class OpenverseProvider(Provider):
    """Nguồn ảnh CC Openverse — không cần API key (rate limit ẩn danh thấp)."""

    name = "openverse"
    supported_types = {MediaType.IMAGE}
    requires_api_key = False

    def __init__(self, api_key: str = "", client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30)

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Tìm ảnh CC trên Openverse."""
        if media_type != MediaType.IMAGE:
            return []
        resp = await self._client.get(
            _BASE,
            params={"q": query, "page": page, "page_size": min(per_page, 20)},
            headers=_UA,
        )
        resp.raise_for_status()
        results: list[SearchResult] = []
        for row in resp.json().get("results", []):
            if not row.get("url"):
                continue
            results.append(
                SearchResult(
                    provider=self.name,
                    media_type=MediaType.IMAGE,
                    title=row.get("title") or f"openverse-{row.get('id', '')[:8]}",
                    thumbnail_url=row.get("thumbnail") or "",
                    download_url=row["url"],
                    source_page_url=row.get("foreign_landing_url", ""),
                    license=_license_text(row),
                    author=row.get("creator"),
                    width=row.get("width"),
                    height=row.get("height"),
                    extra={"openverse_id": row.get("id")},
                )
            )
        logger.debug("Openverse: {} kết quả cho '{}'", len(results), query)
        return results

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải ảnh trực tiếp từ URL nguồn."""
        url = result.download_url
        dest = dest_dir / build_filename(self.name, result.title, ext_from_url(url, ".jpg"), url)
        return await download_with_retry(self._client, url, dest, progress_cb, headers=_UA)

    async def health_check(self) -> bool:
        """Kiểm tra kết nối API."""
        try:
            resp = await self._client.get(
                _BASE, params={"q": "test", "page_size": 1}, headers=_UA
            )
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("Openverse health-check lỗi: {}", exc)
            return False
