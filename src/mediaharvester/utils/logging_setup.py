"""Thiết lập logging bằng loguru: console + file xoay vòng trong logs/."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path | None = None, level: str = "INFO") -> None:
    """Cấu hình loguru: console mức `level`, file DEBUG xoay vòng 10 MB, giữ 10 file."""
    log_dir = log_dir or Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level=level)
    logger.add(
        log_dir / "mediaharvester_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="10 MB",
        retention=10,
        encoding="utf-8",
        enqueue=True,
    )
    logger.debug("Logging đã được thiết lập (thư mục: {}).", log_dir)
