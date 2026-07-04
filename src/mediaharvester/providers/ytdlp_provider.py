"""Provider yt-dlp: search YouTube (ytsearchN:) + tải video từ URL bất kỳ.

- Search: chỉ lấy metadata (extract_flat, không tải) → map thành SearchResult.
- Download: format `bestvideo[height<=H][ext=mp4]+bestaudio[ext=m4a]/best`,
  ưu tiên h264, merge mp4, `writeinfojson`, ffmpeg trỏ vendor/ffmpeg.exe.
- Cắt đoạn: `extra["clip_range"] = "hh:mm:ss-hh:mm:ss"` → download_ranges.
- Cookies-from-browser (chrome/edge/firefox) cho X/Instagram — đọc từ config.
- yt-dlp là thư viện blocking → mọi call chạy qua asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from mediaharvester.core.organizer import build_filename
from mediaharvester.providers.base import (
    MediaType,
    Provider,
    SearchResult,
    register_provider,
)
from mediaharvester.utils.ffmpeg import find_deno, find_ffmpeg

_QUALITY_HEIGHT = {"720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}


def parse_clip_range(clip: str) -> tuple[float, float]:
    """Parse 'hh:mm:ss-hh:mm:ss' (hoặc mm:ss / ss) → (start_sec, end_sec).

    Raise ValueError với thông báo tiếng Việt nếu định dạng sai.
    """

    def to_seconds(text: str) -> float:
        parts = [float(p) for p in text.strip().split(":")]
        if not 1 <= len(parts) <= 3:
            raise ValueError
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        return seconds

    try:
        start_text, end_text = clip.split("-")
        start, end = to_seconds(start_text), to_seconds(end_text)
    except ValueError as exc:
        raise ValueError(
            f"Định dạng đoạn cắt không hợp lệ: '{clip}' — cần dạng hh:mm:ss-hh:mm:ss, "
            "ví dụ 00:01:00-00:01:30"
        ) from exc
    if end <= start:
        raise ValueError(f"Đoạn cắt không hợp lệ: điểm cuối ({end}s) phải sau điểm đầu ({start}s)")
    return start, end


def _entries_to_results(entries: list[dict]) -> list[SearchResult]:
    """Map các entry flat của ytsearch thành SearchResult chuẩn."""
    results: list[SearchResult] = []
    for entry in entries:
        if not entry:
            continue
        video_id = entry.get("id", "")
        url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
        thumbnails = entry.get("thumbnails") or []
        results.append(
            SearchResult(
                provider="ytdlp",
                media_type=MediaType.VIDEO,
                title=entry.get("title") or video_id or "video",
                thumbnail_url=thumbnails[-1]["url"] if thumbnails else "",
                download_url=url,
                source_page_url=url,
                license="unknown (kiểm tra license từng video trên YouTube)",
                author=entry.get("uploader") or entry.get("channel"),
                duration_sec=float(entry["duration"]) if entry.get("duration") else None,
                extra={"ytdlp_id": video_id},
            )
        )
    return results


@register_provider
class YtDlpProvider(Provider):
    """Nguồn video qua yt-dlp: search YouTube + tải URL bất kỳ (YouTube/TikTok/X...)."""

    name = "ytdlp"
    supported_types = {MediaType.VIDEO}
    requires_api_key = False

    def __init__(
        self,
        cookies_from_browser: str | None = None,
        api_key: str = "",
        client: object | None = None,
    ) -> None:
        # api_key/client chỉ để đồng nhất chữ ký khởi tạo với provider khác — không dùng.
        self.cookies_from_browser = cookies_from_browser

    def _base_opts(self) -> dict:
        """Options yt-dlp dùng chung cho mọi thao tác."""
        opts: dict = {"quiet": True, "no_warnings": True, "noprogress": True}
        ffmpeg = find_ffmpeg()
        if ffmpeg is not None:
            opts["ffmpeg_location"] = str(ffmpeg)
        # JS runtime (deno) bắt buộc để YouTube trả URL stream ổn định —
        # thiếu nó URL hay bị đứt giữa chừng (TLS error) → file hỏng/thiếu video.
        deno = find_deno()
        if deno is not None:
            opts["js_runtimes"] = {"deno": {"path": str(deno)}}
        else:
            logger.warning(
                "Không tìm thấy deno (JS runtime) — YouTube có thể tải lỗi. "
                "Chạy: uv run python scripts/fetch_vendor.py"
            )
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        return opts

    # ---------- Search ----------

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Tìm trên YouTube bằng ytsearchN: — chỉ lấy metadata, không tải."""
        if media_type != MediaType.VIDEO:
            return []
        return await asyncio.to_thread(self._search_sync, query, per_page)

    def _search_sync(self, query: str, n: int) -> list[SearchResult]:
        import yt_dlp

        opts = self._base_opts() | {"extract_flat": "in_playlist"}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
        entries = (info or {}).get("entries") or []
        results = _entries_to_results(entries)
        logger.debug("ytdlp: {} kết quả cho '{}'", len(results), query)
        return results

    # ---------- Resolve URL trực tiếp ----------

    async def resolve_url(self, url: str, clip: str | None = None) -> SearchResult:
        """Dán URL bất kỳ → probe metadata (không tải) → SearchResult để đưa vào queue."""
        if clip:
            parse_clip_range(clip)  # validate sớm, báo lỗi thân thiện trước khi tải
        info = await asyncio.to_thread(self._probe_sync, url)
        return SearchResult(
            provider=self.name,
            media_type=MediaType.VIDEO,
            title=info.get("title") or urlparse(url).path.strip("/") or "video",
            thumbnail_url=info.get("thumbnail") or "",
            download_url=url,
            source_page_url=info.get("webpage_url") or url,
            license=info.get("license") or "unknown",
            author=info.get("uploader") or info.get("channel"),
            width=info.get("width"),
            height=info.get("height"),
            duration_sec=float(info["duration"]) if info.get("duration") else None,
            extra={"clip_range": clip} if clip else {},
        )

    def _probe_sync(self, url: str) -> dict:
        import yt_dlp

        with yt_dlp.YoutubeDL(self._base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        return info or {}

    # ---------- Download ----------

    def build_ydl_opts(self, dest_base: Path, quality: str, clip: str | None) -> dict:
        """Dựng options download: format theo quality, ưu tiên h264, infojson, cắt đoạn."""
        height = _QUALITY_HEIGHT.get(quality, 1080)
        opts = self._base_opts() | {
            "format": (
                f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
                f"/best[height<={height}]/best"
            ),
            "format_sort": ["vcodec:h264"],
            "merge_output_format": "mp4",
            "outtmpl": str(dest_base) + ".%(ext)s",
            "writeinfojson": True,
        }
        if clip:
            from yt_dlp.utils import download_range_func

            start, end = parse_clip_range(clip)
            opts["download_ranges"] = download_range_func(None, [(start, end)])
            opts["force_keyframes_at_cuts"] = True
        return opts

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải video (blocking yt-dlp chạy trong thread riêng)."""
        return await asyncio.to_thread(
            self._download_sync, result, dest_dir, progress_cb, quality
        )

    def _download_sync(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str,
    ) -> Path:
        import yt_dlp

        clip = result.extra.get("clip_range")
        # shortid tính cả clip để đoạn cắt không đè lên file video đầy đủ cùng URL
        uid_source = result.download_url + (f"#clip={clip}" if clip else "")
        base_name = build_filename(self.name, result.title, "", uid_source)
        dest_base = dest_dir / base_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        opts = self.build_ydl_opts(dest_base, quality, clip)

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                progress_cb(d.get("downloaded_bytes", 0), int(total))

        opts["progress_hooks"] = [hook]

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([result.download_url])

        final = dest_dir / f"{base_name}.mp4"
        if final.exists():
            return final
        # merge_output_format=mp4 nhưng đề phòng ext khác (vd chỉ có webm)
        candidates = [
            p
            for p in dest_dir.glob(f"{base_name}.*")
            if p.suffix not in (".json", ".part") and not p.name.endswith(".info.json")
        ]
        if candidates:
            return candidates[0]
        raise FileNotFoundError(
            f"yt-dlp không tạo ra file video cho {result.download_url} — xem log chi tiết"
        )

    async def health_check(self) -> bool:
        """yt-dlp không cần key — kiểm tra import thành công."""
        try:
            import yt_dlp  # noqa: F401

            return True
        except ImportError:
            return False
