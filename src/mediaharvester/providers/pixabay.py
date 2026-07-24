"""Provider Pixabay: ảnh + video (https://pixabay.com/api/docs/).

- Auth: query param `key`.
- Ảnh: GET /api/ — tải `largeImageURL` (1280px).
- Video: GET /api/videos/ — chọn size (large/medium/small/tiny) theo quality.
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
    SearchResult,
    register_provider,
)
from mediaharvester.providers.keyed import KeyedProvider

_BASE = "https://pixabay.com/api/"
_LICENSE = "Pixabay Content License"
_QUALITY_HEIGHT = {"720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}
_SIZE_ORDER = ["large", "medium", "small", "tiny"]


def _pick_video_variant(videos: dict, quality: str) -> dict | None:
    """Chọn variant có height ≤ target lớn nhất; không có thì variant nhỏ nhất."""
    target = _QUALITY_HEIGHT.get(quality, 1080)
    variants = [
        v for name in _SIZE_ORDER if (v := videos.get(name)) and v.get("url") and v.get("height")
    ]
    if not variants:
        return None
    under = [v for v in variants if v["height"] <= target]
    if under:
        return max(under, key=lambda v: v["height"])
    return min(variants, key=lambda v: v["height"])


@register_provider
class PixabayProvider(KeyedProvider):
    """Nguồn stock Pixabay — ảnh và video miễn phí, Pixabay Content License."""

    name = "pixabay"
    supported_types = {MediaType.IMAGE, MediaType.VIDEO}
    requires_api_key = True

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Tìm ảnh/video trên Pixabay, trả về danh sách SearchResult chuẩn hóa."""
        per_page = max(3, min(per_page, 200))  # Pixabay yêu cầu 3..200
        params: dict = {"q": query, "page": page, "per_page": per_page,
                        "safesearch": "true"}
        if media_type == MediaType.IMAGE:
            url = _BASE
            params["image_type"] = "photo"
        else:
            url = f"{_BASE}videos/"

        resp = await self._request(
            lambda key: self._client.get(url, params={**params, "key": key})
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[SearchResult] = []
        for hit in data.get("hits", []):
            title = (hit.get("tags") or f"pixabay-{hit['id']}").strip()
            if media_type == MediaType.IMAGE:
                results.append(
                    SearchResult(
                        provider=self.name,
                        media_type=MediaType.IMAGE,
                        title=title,
                        thumbnail_url=hit.get("webformatURL", ""),
                        download_url=hit.get("largeImageURL", ""),
                        source_page_url=hit.get("pageURL", ""),
                        license=_LICENSE,
                        author=hit.get("user"),
                        width=hit.get("imageWidth"),
                        height=hit.get("imageHeight"),
                        extra={"pixabay_id": hit["id"]},
                    )
                )
            else:
                videos = hit.get("videos", {})
                default = _pick_video_variant(videos, "1080p") or {}
                thumb = default.get("thumbnail", "") or (videos.get("medium") or {}).get(
                    "thumbnail", ""
                )
                results.append(
                    SearchResult(
                        provider=self.name,
                        media_type=MediaType.VIDEO,
                        title=title,
                        thumbnail_url=thumb,
                        download_url=default.get("url", ""),
                        source_page_url=hit.get("pageURL", ""),
                        license=_LICENSE,
                        author=hit.get("user"),
                        width=default.get("width"),
                        height=default.get("height"),
                        duration_sec=float(hit["duration"]) if hit.get("duration") else None,
                        extra={"pixabay_id": hit["id"], "videos": videos},
                    )
                )
        logger.debug("Pixabay: {} kết quả cho '{}' ({})", len(results), query, media_type)
        return results

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải file về `dest_dir`; video chọn lại variant theo `quality` từ extra."""
        url = result.download_url
        if result.media_type == MediaType.VIDEO and result.extra.get("videos"):
            picked = _pick_video_variant(result.extra["videos"], quality)
            if picked and picked.get("url"):
                url = picked["url"]
        default_ext = ".jpg" if result.media_type == MediaType.IMAGE else ".mp4"
        dest = dest_dir / build_filename(
            self.name, result.title, ext_from_url(url, default_ext), url
        )
        return await download_with_retry(self._client, url, dest, progress_cb)

    async def health_check(self) -> bool:
        """Kiểm tra API key (có xoay vòng) bằng 1 request search tối thiểu."""
        try:
            resp = await self._request(
                lambda key: self._client.get(
                    _BASE, params={"key": key, "q": "test", "per_page": 3}
                )
            )
            return resp.status_code == 200
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.warning("Pixabay health-check lỗi: {}", exc)
            return False
