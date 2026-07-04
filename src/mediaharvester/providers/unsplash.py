"""Provider Unsplash: ảnh chất lượng cao (https://unsplash.com/documentation).

- Auth: header `Authorization: Client-ID <access_key>`.
- Theo API guideline: khi tải phải gọi `links.download_location` để Unsplash
  đếm lượt download, rồi mới tải URL trả về.
"""

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

_BASE = "https://api.unsplash.com"
_LICENSE = "Unsplash License"


@register_provider
class UnsplashProvider(Provider):
    """Nguồn ảnh Unsplash — cần access key (50 request/giờ bản demo)."""

    name = "unsplash"
    supported_types = {MediaType.IMAGE}
    requires_api_key = True

    def __init__(self, api_key: str = "", client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=30)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Client-ID {self.api_key}"}

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Tìm ảnh trên Unsplash."""
        if media_type != MediaType.IMAGE:
            return []
        resp = await self._client.get(
            f"{_BASE}/search/photos",
            params={"query": query, "page": page, "per_page": min(per_page, 30)},
            headers=self._headers(),
        )
        resp.raise_for_status()
        results: list[SearchResult] = []
        for photo in resp.json().get("results", []):
            title = (
                photo.get("description")
                or photo.get("alt_description")
                or f"unsplash-{photo['id']}"
            )
            results.append(
                SearchResult(
                    provider=self.name,
                    media_type=MediaType.IMAGE,
                    title=title,
                    thumbnail_url=photo["urls"].get("small", ""),
                    download_url=photo["urls"].get("full", ""),
                    source_page_url=photo["links"].get("html", ""),
                    license=_LICENSE,
                    author=(photo.get("user") or {}).get("name"),
                    width=photo.get("width"),
                    height=photo.get("height"),
                    extra={
                        "unsplash_id": photo["id"],
                        "download_location": photo["links"].get("download_location", ""),
                    },
                )
            )
        logger.debug("Unsplash: {} kết quả cho '{}'", len(results), query)
        return results

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải ảnh; gọi download_location trước theo guideline của Unsplash."""
        url = result.download_url
        location = result.extra.get("download_location")
        if location:
            try:
                resp = await self._client.get(location, headers=self._headers())
                resp.raise_for_status()
                url = resp.json().get("url") or url
            except httpx.HTTPError as exc:
                logger.warning("Unsplash download_location lỗi ({}) — dùng URL gốc.", exc)
        dest = dest_dir / build_filename(self.name, result.title, ext_from_url(url, ".jpg"), url)
        return await download_with_retry(self._client, url, dest, progress_cb)

    async def health_check(self) -> bool:
        """Kiểm tra access key bằng 1 request search tối thiểu."""
        try:
            resp = await self._client.get(
                f"{_BASE}/search/photos",
                params={"query": "test", "per_page": 1},
                headers=self._headers(),
            )
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("Unsplash health-check lỗi: {}", exc)
            return False
