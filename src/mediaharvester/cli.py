"""Entry point CLI của MediaHarvester.

Phase 0: chỉ có --version / --help. Lệnh `search` sẽ được thêm ở Phase 1.
"""

from __future__ import annotations

import argparse
import sys

from mediaharvester import __version__
from mediaharvester.utils.logging_setup import setup_logging


def _force_utf8_console() -> None:
    """Ép stdout/stderr sang UTF-8 để in được tiếng Việt trên console Windows (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    """Tạo argument parser cho CLI."""
    parser = argparse.ArgumentParser(
        prog="mediaharvester-cli",
        description=(
            "MediaHarvester — tìm kiếm & tải hàng loạt ảnh/video từ nhiều nguồn "
            "internet làm tài nguyên edit video."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Chạy CLI. Trả về exit code."""
    _force_utf8_console()
    setup_logging()
    parser = build_parser()
    parser.parse_args(argv)
    # Phase 0: chưa có subcommand — hiển thị help khi chạy không tham số.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
