"""Provider NASA Image and Video Library (https://images.nasa.gov) — không cần key.

Search trả về manifest (collection.json); lúc download mới resolve manifest
để chọn file gốc (~orig) hoặc bản lớn nhất khả dụng.
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

_BASE = "https://images-api.nasa.gov"
_LICENSE = "Public Domain (NASA)"


def pick_asset_url(urls: list[str], media_type: MediaType) -> str | None:
    """Chọn URL tốt nhất từ manifest: ưu tiên ~orig, rồi ~large; video phải .mp4."""
    if media_type == MediaType.VIDEO:
        candidates = [u for u in urls if u.lower().endswith(".mp4")]
    else:
        candidates = [
            u for u in urls if u.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff"))
        ]
    if not candidates:
        return None
    for marker in ("~orig", "~large", "~medium"):
        for url in candidates:
            if marker in url.lower():
                return url
    return candidates[0]


@register_provider
class NasaProvider(Provider):
    """Nguồn NASA Image Library — ảnh/video Public Domain, không cần key."""

    name = "nasa"
    supported_types = {MediaType.IMAGE, MediaType.VIDEO}
    requires_api_key = False

    def __init__(self, api_key: str = "", client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30)

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Tìm trên NASA Image Library."""
        resp = await self._client.get(
            f"{_BASE}/search",
            params={"q": query, "media_type": media_type.value, "page": page},
        )
        resp.raise_for_status()
        items = (resp.json().get("collection") or {}).get("items") or []
        results: list[SearchResult] = []
        for item in items[:per_page]:
            data_list = item.get("data") or []
            if not data_list:
                continue
            data = data_list[0]
            links = item.get("links") or []
            thumb = next((ln.get("href", "") for ln in links if ln.get("rel") == "preview"), "")
            nasa_id = data.get("nasa_id", "")
            results.append(
                SearchResult(
                    provider=self.name,
                    media_type=media_type,
                    title=data.get("title") or nasa_id,
                    thumbnail_url=thumb,
                    download_url=item.get("href", ""),  # manifest — resolve khi download
                    source_page_url=f"https://images.nasa.gov/details/{nasa_id}",
                    license=_LICENSE,
                    author=data.get("photographer") or data.get("secondary_creator"),
                    extra={"nasa_id": nasa_id, "manifest": item.get("href", "")},
                )
            )
        logger.debug("NASA: {} kết quả cho '{}' ({})", len(results), query, media_type)
        return results

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Resolve manifest → chọn file ~orig → tải."""
        manifest_url = result.extra.get("manifest") or result.download_url
        resp = await self._client.get(manifest_url)
        resp.raise_for_status()
        urls = [u.replace("http://", "https://") for u in resp.json() if isinstance(u, str)]
        url = pick_asset_url(urls, MediaType(result.media_type))
        if url is None:
            raise ValueError(f"NASA manifest không có file phù hợp: {manifest_url}")
        default_ext = ".jpg" if result.media_type == MediaType.IMAGE else ".mp4"
        dest = dest_dir / build_filename(
            self.name, result.title, ext_from_url(url, default_ext), url
        )
        return await download_with_retry(self._client, url, dest, progress_cb)

    async def health_check(self) -> bool:
        """Kiểm tra kết nối API."""
        try:
            resp = await self._client.get(f"{_BASE}/search", params={"q": "moon", "page": 1})
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("NASA health-check lỗi: {}", exc)
            return False
