"""ThumbnailLoader: tải thumbnail async qua httpx, cache đĩa + QPixmapCache.

- Không tải lại thumbnail đã có trong cache đĩa (.thumbcache/).
- Không giữ toàn bộ ảnh trong RAM: QPixmapCache có giới hạn, ảnh load từ đĩa.
- Chạy trong event loop qasync (cùng thread GUI) → emit signal trực tiếp an toàn.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import httpx
from loguru import logger
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap, QPixmapCache

# Giới hạn QPixmapCache ~64 MB (đơn vị KB)
QPixmapCache.setCacheLimit(64 * 1024)


def load_pixmap_cached(path: str, max_edge: int = 320) -> QPixmap:
    """Load pixmap từ đĩa qua QPixmapCache (key = đường dẫn file)."""
    pixmap = QPixmapCache.find(path)
    if pixmap is not None and not pixmap.isNull():
        return pixmap
    pixmap = QPixmap(path)
    if not pixmap.isNull() and max(pixmap.width(), pixmap.height()) > max_edge:
        pixmap = pixmap.scaled(
            max_edge,
            max_edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    QPixmapCache.insert(path, pixmap)
    return pixmap


class ThumbnailLoader(QObject):
    """Tải thumbnail theo URL về cache đĩa rồi phát signal cho grid cập nhật icon."""

    thumb_ready = Signal(int, str)  # (row, đường dẫn file cache)

    def __init__(self, client: httpx.AsyncClient, cache_dir: Path) -> None:
        super().__init__()
        self._client = client
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._sem = asyncio.Semaphore(8)

    def cache_path(self, url: str) -> Path:
        """Đường dẫn file cache theo hash URL."""
        return self._cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.img"

    async def fetch(self, row: int, url: str) -> None:
        """Tải 1 thumbnail (bỏ qua nếu đã cache); lỗi mạng chỉ log, không crash."""
        if not url:
            return
        path = self.cache_path(url)
        if not path.exists():
            try:
                async with self._sem:
                    resp = await self._client.get(url, follow_redirects=True)
                    resp.raise_for_status()
                path.write_bytes(resp.content)
            except (httpx.HTTPError, RuntimeError, OSError) as exc:
                # RuntimeError: client đã đóng khi app thoát giữa chừng
                logger.debug("Không tải được thumbnail {}: {}", url, exc)
                return
        self.thumb_ready.emit(row, str(path))

    def fetch_many(self, urls: list[tuple[int, str]]) -> None:
        """Lên lịch tải hàng loạt (row, url) — fire & forget trong event loop."""
        for row, url in urls:
            asyncio.ensure_future(self.fetch(row, url))
