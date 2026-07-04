"""Provider gallery-dl: tải gallery/ảnh MXH từ URL qua subprocess.

Theo spec, gallery-dl chạy bằng subprocess (`python -m gallery_dl`) — đây là
ngoại lệ được phép. Provider này không hỗ trợ search theo từ khóa; vai trò của
nó là nhận URL gallery (Twitter/X, Instagram, DeviantArt...) và tải toàn bộ.
Nếu file `gallery-dl.conf.json` tồn tại ở thư mục dự án thì được dùng làm config.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from mediaharvester.providers.base import (
    MediaType,
    Provider,
    SearchResult,
    register_provider,
)

_CONFIG_FILE = Path("gallery-dl.conf.json")


@register_provider
class GalleryDlProvider(Provider):
    """Tải gallery ảnh MXH qua gallery-dl (subprocess). Không hỗ trợ search."""

    name = "gallerydl"
    supported_types = {MediaType.IMAGE}
    requires_api_key = False

    def __init__(self, api_key: str = "", client: object | None = None) -> None:
        # Nhận kwargs để đồng nhất chữ ký khởi tạo — không dùng.
        pass

    @staticmethod
    def make_result(url: str) -> SearchResult:
        """Tạo SearchResult từ URL gallery để đưa vào DownloadManager."""
        return SearchResult(
            provider="gallerydl",
            media_type=MediaType.IMAGE,
            title=url.rstrip("/").rsplit("/", 1)[-1] or "gallery",
            thumbnail_url="",
            download_url=url,
            source_page_url=url,
            license="unknown (ảnh MXH — tự kiểm tra bản quyền)",
        )

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """gallery-dl không hỗ trợ search từ khóa — chỉ tải theo URL."""
        logger.info("gallery-dl không hỗ trợ search — dán URL gallery để tải.")
        return []

    def _base_cmd(self) -> list[str]:
        cmd = [sys.executable, "-m", "gallery_dl"]
        if _CONFIG_FILE.exists():
            cmd += ["--config", str(_CONFIG_FILE)]
        return cmd

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải toàn bộ gallery vào dest_dir; trả về file đầu tiên tải được."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        before = {p for p in dest_dir.rglob("*") if p.is_file()}

        cmd = self._base_cmd() + [
            "--dest", str(dest_dir),
            "--write-info-json",
            result.download_url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        output = out.decode(errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(
                f"gallery-dl thất bại (mã {proc.returncode}): {output[-400:]}"
            )

        new_files = sorted(
            p for p in dest_dir.rglob("*")
            if p.is_file() and p not in before and not p.name.endswith(".json")
        )
        if not new_files:
            raise RuntimeError(f"gallery-dl không tải được file nào từ {result.download_url}")
        logger.info("gallery-dl: tải {} file từ {}", len(new_files), result.download_url)
        progress_cb(len(new_files), len(new_files))
        return new_files[0]

    async def health_check(self) -> bool:
        """OK nếu `python -m gallery_dl --version` chạy được."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *[sys.executable, "-m", "gallery_dl", "--version"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
            return proc.returncode == 0
        except (OSError, TimeoutError) as exc:
            logger.warning("gallery-dl health-check lỗi: {}", exc)
            return False
