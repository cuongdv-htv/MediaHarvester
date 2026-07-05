"""Entry point GUI: PySide6 + qasync (asyncio event loop chung với Qt)."""

from __future__ import annotations

import asyncio
import multiprocessing
import sys
import traceback
from pathlib import Path

from mediaharvester.utils.logging_setup import setup_logging


def _run() -> int:
    """Khởi động GUI MediaHarvester (phần chính, được _guard bọc bắt lỗi)."""
    setup_logging()

    import qasync
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("MediaHarvester")

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    from mediaharvester.gui.main_window import MainWindow

    window = MainWindow()
    window.show()

    async def _shutdown() -> None:
        """Dọn dẹp khi thoát: dừng worker pool + đóng HTTP client."""
        await window.manager.stop()
        await window.client.aclose()

    with loop:
        loop.run_forever()
        loop.run_until_complete(_shutdown())
    return 0


def main() -> int:
    """Entry point: bắt mọi lỗi khởi động ghi ra logs/startup_error.log.

    Bản đóng gói (windowed) không có console — nếu app crash lúc khởi động,
    traceback phải được ghi ra file để còn chẩn đoán được.
    """
    # PyInstaller + multiprocessing: tránh child process re-exec toàn bộ app.
    multiprocessing.freeze_support()
    try:
        return _run()
    except Exception:
        tb = traceback.format_exc()
        try:
            Path("logs").mkdir(exist_ok=True)
            (Path("logs") / "startup_error.log").write_text(tb, encoding="utf-8")
        except OSError:
            pass
        print(tb, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
