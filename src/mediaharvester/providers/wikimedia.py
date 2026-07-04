"""Provider Wikimedia Commons: ảnh + video (MediaWiki API) — không cần key."""

from __future__ import annotations

import re
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

_API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia yêu cầu UA định danh rõ ràng
_UA = {"User-Agent": "MediaHarvester/0.1 (https://github.com/cuongdv-htv/MediaHarvester)"}
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Bỏ tag HTML trong giá trị extmetadata (Artist thường là HTML)."""
    return _TAG_RE.sub("", text).strip()


@register_provider
class WikimediaProvider(Provider):
    """Nguồn Wikimedia Commons — ảnh/video license mở, không cần API key."""

    name = "wikimedia"
    supported_types = {MediaType.IMAGE, MediaType.VIDEO}
    requires_api_key = False

    def __init__(self, api_key: str = "", client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30)

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Tìm file trên Commons qua generator=search namespace File."""
        per_page = min(per_page, 50)
        filetype = "bitmap|drawing" if media_type == MediaType.IMAGE else "video"
        resp = await self._client.get(
            _API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:{filetype} {query}",
                "gsrnamespace": 6,
                "gsrlimit": per_page,
                "gsroffset": (page - 1) * per_page,
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": 320,
            },
            headers=_UA,
        )
        resp.raise_for_status()
        pages = (resp.json().get("query") or {}).get("pages") or {}
        results: list[SearchResult] = []
        for page_data in pages.values():
            infos = page_data.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            meta = info.get("extmetadata") or {}
            license_name = (meta.get("LicenseShortName") or {}).get("value", "unknown")
            artist_raw = (meta.get("Artist") or {}).get("value", "")
            results.append(
                SearchResult(
                    provider=self.name,
                    media_type=media_type,
                    title=page_data.get("title", "").removeprefix("File:"),
                    thumbnail_url=info.get("thumburl", ""),
                    download_url=info.get("url", ""),
                    source_page_url=info.get("descriptionurl", ""),
                    license=license_name,
                    author=_strip_html(artist_raw) or None,
                    width=info.get("width"),
                    height=info.get("height"),
                    extra={"mime": info.get("mime")},
                )
            )
        logger.debug("Wikimedia: {} kết quả cho '{}' ({})", len(results), query, media_type)
        return results

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải file gốc từ upload.wikimedia.org."""
        url = result.download_url
        default_ext = ".jpg" if result.media_type == MediaType.IMAGE else ".webm"
        dest = dest_dir / build_filename(
            self.name, result.title, ext_from_url(url, default_ext), url
        )
        return await download_with_retry(self._client, url, dest, progress_cb, headers=_UA)

    async def health_check(self) -> bool:
        """Kiểm tra kết nối API Commons."""
        try:
            resp = await self._client.get(
                _API,
                params={"action": "query", "format": "json", "meta": "siteinfo"},
                headers=_UA,
            )
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("Wikimedia health-check lỗi: {}", exc)
            return False
