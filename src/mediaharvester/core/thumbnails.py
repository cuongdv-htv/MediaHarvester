"""Thumbnail: Pillow cho ảnh + ffmpeg extract frame cho video.

Thumbnail lưu tập trung tại {library_root}/.thumbnails/{tên file gốc}.jpg —
GUI (Phase 3) đọc từ đây, không tải lại thumbnail đã cache.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from loguru import logger
from PIL import Image

from mediaharvester.utils.ffmpeg import extract_frame

THUMB_SIZE = (320, 320)


def make_image_thumbnail(
    src: Path, dest_dir: Path, size: tuple[int, int] = THUMB_SIZE
) -> Path | None:
    """Tạo thumbnail JPEG cho ảnh; lỗi → None (log warning, không crash)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{src.stem}.jpg"
    try:
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.thumbnail(size)
            img.save(dest, "JPEG", quality=85)
        return dest
    except Exception as exc:
        logger.warning("Không tạo được thumbnail cho {}: {}", src.name, exc)
        return None


def make_thumbnail(asset_path: Path, media_type: str, dest_dir: Path) -> Path | None:
    """Tạo thumbnail cho asset theo loại media. Trả về đường dẫn thumb hoặc None."""
    if media_type == "image":
        return make_image_thumbnail(asset_path, dest_dir)
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / f"{asset_path.stem}.png"
        if not extract_frame(asset_path, frame, at_sec=1.0):
            return None
        return make_image_thumbnail(frame, dest_dir)
