"""MainWindow: QTabWidget 4 tab Search / Queue / Library / Settings + statusbar toast.

Kiến trúc:
- Mọi I/O chạy async trong event loop qasync (không block UI thread).
- DownloadManager phát progress qua QueueBridge (Qt Signal) — an toàn kể cả khi
  callback đến từ thread của yt-dlp (Qt tự queue connection xuyên thread).
"""

from __future__ import annotations

import httpx
from loguru import logger
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMainWindow, QTabWidget

from mediaharvester.core.config import ApiKeys, load_config
from mediaharvester.core.database import get_engine, init_db
from mediaharvester.core.downloader import DownloadManager
from mediaharvester.providers.base import Provider, get_registry


class QueueBridge(QObject):
    """Cầu nối thread-safe: DownloadManager callback → Qt Signal → GUI slots."""

    job_updated = Signal(object)  # JobState


class MainWindow(QMainWindow):
    """Cửa sổ chính MediaHarvester."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MediaHarvester — thu thập tài nguyên edit video")
        self.resize(1280, 800)

        # ---------- Hạ tầng dùng chung ----------
        self.config = load_config()
        self.api_keys = ApiKeys()
        self.engine = get_engine(self.config.library_root / "mediaharvester.db")
        init_db(self.engine)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0))
        self.providers = self._build_providers()

        self.bridge = QueueBridge()
        self.manager = DownloadManager(
            self.config,
            self.engine,
            self.providers,
            project_name="default",
            progress_cb=self.bridge.job_updated.emit,
        )

        # ---------- Widgets (import trễ để tránh vòng lặp import) ----------
        from mediaharvester.gui.library_tab import LibraryTab
        from mediaharvester.gui.queue_tab import QueueTab
        from mediaharvester.gui.search_tab import SearchTab
        from mediaharvester.gui.settings_tab import SettingsTab
        from mediaharvester.gui.widgets.thumbs import ThumbnailLoader

        self.thumb_loader = ThumbnailLoader(
            self.client, self.config.library_root / ".thumbcache"
        )

        self.tabs = QTabWidget()
        self.library_tab = LibraryTab(self)
        self.search_tab = SearchTab(self)
        self.queue_tab = QueueTab(self)
        self.settings_tab = SettingsTab(self)
        self.tabs.addTab(self.search_tab, "🔍 Tìm kiếm")
        self.tabs.addTab(self.queue_tab, "⬇ Hàng đợi")
        self.tabs.addTab(self.library_tab, "🗂 Thư viện")
        self.tabs.addTab(self.settings_tab, "⚙ Cài đặt")
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage("Sẵn sàng.")

        self.bridge.job_updated.connect(self.queue_tab.on_job_updated)

        # Worker pool cần loop đang chạy → khởi động sau khi event loop bắt đầu
        QTimer.singleShot(0, self.manager.start)

    # ---------- Helpers ----------

    def _build_providers(self) -> dict[str, Provider]:
        """Khởi tạo mọi provider khả dụng từ registry (thiếu key thì bỏ qua)."""
        from mediaharvester.providers import pexels, pixabay, ytdlp_provider  # noqa: F401

        key_map = {
            "pexels": self.api_keys.pexels_api_key,
            "pixabay": self.api_keys.pixabay_api_key,
            "unsplash": self.api_keys.unsplash_access_key,
        }
        providers: dict[str, Provider] = {}
        for name, cls in get_registry().items():
            api_key = key_map.get(name, "")
            if cls.requires_api_key and not api_key:
                logger.warning("Thiếu API key cho provider {} — bỏ qua.", name)
                continue
            try:
                if name == "ytdlp":
                    providers[name] = cls(
                        cookies_from_browser=self.config.ytdlp.cookies_from_browser
                    )
                else:
                    providers[name] = cls(api_key=api_key, client=self.client)
            except Exception as exc:
                # Provider hỏng không được phép làm app chết
                logger.warning("Không khởi tạo được provider {}: {} — bỏ qua.", name, exc)
        return providers

    def toast(self, message: str) -> None:
        """Hiện thông báo ngắn trên statusbar (không popup làm phiền)."""
        self.statusBar().showMessage(message, 6000)
        logger.info("[toast] {}", message)

    def jobs_changed(self) -> None:
        """Gọi sau khi thêm job mới để Queue tab tạo hàng."""
        self.queue_tab.sync_rows()
