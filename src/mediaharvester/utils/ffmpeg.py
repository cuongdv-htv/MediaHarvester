"""Wrapper tiện ích cho ffmpeg (bundle trong vendor/ từ Phase 2)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from loguru import logger

from mediaharvester.utils.paths import vendor_dir


def _find_vendor_tool(exe_name: str, path_name: str) -> Path | None:
    """Tìm tool: ưu tiên vendor/{exe_name} (kể cả khi đóng gói), fallback PATH."""
    vendor_exe = vendor_dir() / exe_name
    if vendor_exe.exists():
        return vendor_exe
    which = shutil.which(path_name)
    return Path(which) if which else None


def find_ffmpeg() -> Path | None:
    """Tìm ffmpeg: ưu tiên vendor/ffmpeg.exe, fallback ffmpeg trong PATH."""
    return _find_vendor_tool("ffmpeg.exe", "ffmpeg")


def find_deno() -> Path | None:
    """Tìm deno (JS runtime cho yt-dlp/YouTube): vendor/deno.exe, fallback PATH."""
    return _find_vendor_tool("deno.exe", "deno")


def find_gallery_dl() -> Path | None:
    """Tìm gallery-dl.exe trong vendor/ (cần cho bản đóng gói); None nếu chưa có."""
    vendor_exe = vendor_dir() / "gallery-dl.exe"
    return vendor_exe if vendor_exe.exists() else None


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
