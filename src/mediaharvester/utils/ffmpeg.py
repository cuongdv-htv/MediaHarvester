"""Wrapper tiện ích cho ffmpeg (bundle trong vendor/ từ Phase 2)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from loguru import logger

VENDOR_FFMPEG = Path("vendor") / "ffmpeg.exe"


def find_ffmpeg() -> Path | None:
    """Tìm ffmpeg: ưu tiên vendor/ffmpeg.exe, fallback ffmpeg trong PATH."""
    if VENDOR_FFMPEG.exists():
        return VENDOR_FFMPEG
    which = shutil.which("ffmpeg")
    return Path(which) if which else None


def extract_frame(video_path: Path, output_png: Path, at_sec: float = 1.0) -> bool:
    """Trích 1 frame tại giây `at_sec` ra file PNG. Trả về False nếu thiếu ffmpeg/lỗi.

    Hàm blocking — caller trong async context phải gọi qua asyncio.to_thread.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        logger.warning("Không tìm thấy ffmpeg — bỏ qua trích frame video (sẽ có ở Phase 2).")
        return False
    try:
        result = subprocess.run(
            [
                str(ffmpeg), "-y", "-loglevel", "error",
                "-ss", str(at_sec), "-i", str(video_path),
                "-frames:v", "1", str(output_png),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning("ffmpeg trích frame lỗi ({}): {}", video_path.name, result.stderr[:300])
            return False
        return output_png.exists()
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Không chạy được ffmpeg: {}", exc)
        return False
