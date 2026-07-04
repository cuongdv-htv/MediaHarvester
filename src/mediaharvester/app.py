"""Entry point GUI: PySide6 + qasync (asyncio event loop chung với Qt)."""

from __future__ import annotations

import asyncio
import sys

from mediaharvester.utils.logging_setup import setup_logging


def main() -> int:
    """Khởi động GUI MediaHarvester."""
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


if __name__ == "__main__":
    raise SystemExit(main())
