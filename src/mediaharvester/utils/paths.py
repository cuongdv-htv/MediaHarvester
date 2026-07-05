"""Đường dẫn gốc của app — hoạt động cả khi chạy dev lẫn khi đóng gói PyInstaller."""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Thư mục gốc chứa vendor/, config.toml...

    - Chạy dev: thư mục làm việc hiện tại (project root).
    - Đóng gói (PyInstaller onedir): thư mục chứa file .exe.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def vendor_dir() -> Path:
    """Thư mục vendor/ chứa ffmpeg.exe, yt-dlp.exe, deno.exe, gallery-dl.exe.

    Bản đóng gói PyInstaller 6 đặt datas trong `_internal/` (sys._MEIPASS) —
    ưu tiên chỗ đó, fallback vendor/ cạnh exe (Nuitka/dev).
    """
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", app_dir()))
        bundled = meipass / "vendor"
        if bundled.exists():
            return bundled
    return app_dir() / "vendor"
