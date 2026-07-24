"""Provider Pexels: ảnh + video (https://www.pexels.com/api/).

- Auth: header `Authorization: <API key>`.
- Ảnh: GET /v1/search — tải bản `original`.
- Video: GET /videos/search — chọn file mp4 có height ≤ quality yêu cầu, lớn nhất.
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

_BASE = "https://api.pexels.com"
_LICENSE = "Pexels License"
_QUALITY_HEIGHT = {"720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}


def _pick_video_file(video_files: list[dict], quality: str) -> dict | None:
    """Chọn file mp4 có height ≤ target lớn nhất; không có thì lấy nhỏ nhất khả dụng."""
    target = _QUALITY_HEIGHT.get(quality, 1080)
    candidates = [
        f for f in video_files if f.get("height") and f.get("file_type") == "video/mp4"
    ] or [f for f in video_files if f.get("height")]
    if not candidates:
        return video_files[0] if video_files else None
    under = [f for f in candidates if f["height"] <= target]
    if under:
        return max(under, key=lambda f: f["height"])
    return min(candidates, key=lambda f: f["height"])


@register_provider
class PexelsProvider(KeyedProvider):
    """Nguồn stock Pexels — ảnh và video miễn phí, license Pexels License."""

    name = "pexels"
    supported_types = {MediaType.IMAGE, MediaType.VIDEO}
    requires_api_key = True

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Tìm ảnh/video trên Pexels, trả về danh sách SearchResult chuẩn hóa."""
        per_page = max(1, min(per_page, 80))
        if media_type == MediaType.IMAGE:
            url = f"{_BASE}/v1/search"
        else:
            url = f"{_BASE}/videos/search"
        params = {"query": query, "page": page, "per_page": per_page}
        resp = await self._request(
            lambda key: self._client.get(url, params=params, headers={"Authorization": key})
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[SearchResult] = []
        if media_type == MediaType.IMAGE:
            for photo in data.get("photos", []):
                results.append(
                    SearchResult(
                        provider=self.name,
                        media_type=MediaType.IMAGE,
                        title=photo.get("alt") or f"pexels-photo-{photo['id']}",
                        thumbnail_url=photo["src"].get("medium", ""),
                        download_url=photo["src"].get("original", ""),
                        source_page_url=photo.get("url", ""),
                        license=_LICENSE,
                        author=photo.get("photographer"),
                        width=photo.get("width"),
                        height=photo.get("height"),
                        extra={"pexels_id": photo["id"]},
                    )
                )
        else:
            for video in data.get("videos", []):
                video_files = video.get("video_files", [])
                default = _pick_video_file(video_files, "1080p") or {}
                results.append(
                    SearchResult(
                        provider=self.name,
                        media_type=MediaType.VIDEO,
                        title=f"pexels-video-{video['id']}",
                        thumbnail_url=video.get("image", ""),
                        download_url=default.get("link", ""),
                        source_page_url=video.get("url", ""),
                        license=_LICENSE,
                        author=(video.get("user") or {}).get("name"),
                        width=video.get("width"),
                        height=video.get("height"),
                        duration_sec=float(video["duration"]) if video.get("duration") else None,
                        extra={"pexels_id": video["id"], "video_files": video_files},
                    )
                )
        logger.debug("Pexels: {} kết quả cho '{}' ({})", len(results), query, media_type)
        return results

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải file về `dest_dir`; video chọn lại file theo `quality` từ extra."""
        url = result.download_url
        if result.media_type == MediaType.VIDEO and result.extra.get("video_files"):
            picked = _pick_video_file(result.extra["video_files"], quality)
            if picked and picked.get("link"):
                url = picked["link"]
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
                    f"{_BASE}/v1/search",
                    params={"query": "test", "per_page": 1},
                    headers={"Authorization": key},
                )
            )
            return resp.status_code == 200
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.warning("Pexels health-check lỗi: {}", exc)
            return False
