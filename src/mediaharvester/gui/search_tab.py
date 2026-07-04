"""Tab Search: keywords nhiều dòng, chọn providers, grid thumbnail, thêm vào queue.

- Mỗi dòng trong ô query = 1 keyword; search chạy song song mọi keyword × provider.
- Ô dán URL trực tiếp (YouTube/TikTok/X...) → route sang yt-dlp provider.
- Không block UI: mọi I/O qua qasync (@asyncSlot), thumbnail lazy-load có cache.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from mediaharvester.gui.widgets.result_grid import ResultGrid
from mediaharvester.providers.base import MediaType, SearchResult

if TYPE_CHECKING:
    from mediaharvester.gui.main_window import MainWindow

_MIN_RES_OPTIONS = [
    ("Mọi độ phân giải", 0),
    ("≥ 720p (1280×720)", 720),
    ("≥ 1080p (1920×1080)", 1080),
    ("≥ 4K (3840×2160)", 2160),
]


class SearchTab(QWidget):
    """Tab tìm kiếm media đa nguồn."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window = window
        self._results: list[tuple[SearchResult, str]] = []  # (result, keyword)

        root = QVBoxLayout(self)

        # ---------- Hàng nhập liệu ----------
        top = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Từ khóa (mỗi dòng một từ khóa):"))
        self.query_edit = QPlainTextEdit()
        self.query_edit.setPlaceholderText("solar panel\nwind turbine\nkinh tế vĩ mô...")
        self.query_edit.setFixedHeight(80)
        left.addWidget(self.query_edit)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Hoặc dán URL video (YouTube/TikTok/X...)")
        self.clip_edit = QLineEdit()
        self.clip_edit.setPlaceholderText("Cắt đoạn hh:mm:ss-hh:mm:ss (tùy chọn)")
        self.clip_edit.setFixedWidth(220)
        self.url_btn = QPushButton("Tải URL này")
        url_row.addWidget(self.url_edit)
        url_row.addWidget(self.clip_edit)
        url_row.addWidget(self.url_btn)
        left.addLayout(url_row)
        top.addLayout(left, stretch=3)

        # ---------- Panel tùy chọn ----------
        options = QVBoxLayout()
        provider_box = QGroupBox("Nguồn")
        provider_layout = QVBoxLayout(provider_box)
        self.provider_checks: dict[str, QCheckBox] = {}
        for name in sorted(self.window.providers):
            check = QCheckBox(name)
            check.setChecked(name in ("pexels", "pixabay"))
            provider_layout.addWidget(check)
            self.provider_checks[name] = check
        options.addWidget(provider_box)

        type_box = QGroupBox("Loại")
        type_layout = QHBoxLayout(type_box)
        self.radio_image = QRadioButton("Ảnh")
        self.radio_video = QRadioButton("Video")
        self.radio_both = QRadioButton("Cả hai")
        self.radio_image.setChecked(True)
        for r in (self.radio_image, self.radio_video, self.radio_both):
            type_layout.addWidget(r)
        options.addWidget(type_box)

        self.min_res_combo = QComboBox()
        for label, _ in _MIN_RES_OPTIONS:
            self.min_res_combo.addItem(label)
        options.addWidget(QLabel("Độ phân giải tối thiểu:"))
        options.addWidget(self.min_res_combo)

        options.addWidget(QLabel("Project:"))
        self.project_edit = QLineEdit("default")
        options.addWidget(self.project_edit)

        self.search_btn = QPushButton("🔍 Tìm kiếm")
        self.search_btn.setDefault(True)
        options.addWidget(self.search_btn)
        options.addStretch()
        top.addLayout(options, stretch=1)
        root.addLayout(top)

        # ---------- Kết quả ----------
        self.count_label = QLabel("Chưa có kết quả.")
        root.addWidget(self.count_label)
        self.grid = ResultGrid(checkable=True)
        root.addWidget(self.grid, stretch=1)

        bottom = QHBoxLayout()
        self.check_all_btn = QPushButton("Chọn tất cả")
        self.uncheck_all_btn = QPushButton("Bỏ chọn")
        self.add_queue_btn = QPushButton("➕ Thêm mục đã chọn vào hàng đợi")
        bottom.addWidget(self.check_all_btn)
        bottom.addWidget(self.uncheck_all_btn)
        bottom.addStretch()
        bottom.addWidget(self.add_queue_btn)
        root.addLayout(bottom)

        # ---------- Nối signal ----------
        self.search_btn.clicked.connect(self.on_search)
        self.url_btn.clicked.connect(self.on_download_url)
        self.check_all_btn.clicked.connect(lambda: self.grid.set_all_checked(True))
        self.uncheck_all_btn.clicked.connect(lambda: self.grid.set_all_checked(False))
        self.add_queue_btn.clicked.connect(self.on_add_to_queue)
        self.window.thumb_loader.thumb_ready.connect(self.grid.set_thumb)

    # ---------- Hành vi ----------

    def _selected_media_types(self) -> list[MediaType]:
        if self.radio_image.isChecked():
            return [MediaType.IMAGE]
        if self.radio_video.isChecked():
            return [MediaType.VIDEO]
        return [MediaType.IMAGE, MediaType.VIDEO]

    def _passes_min_res(self, result: SearchResult) -> bool:
        min_height = _MIN_RES_OPTIONS[self.min_res_combo.currentIndex()][1]
        if min_height == 0 or result.height is None:
            return True  # không rõ resolution thì vẫn hiển thị
        return result.height >= min_height or (result.width or 0) >= min_height * 16 // 9

    @asyncSlot()
    async def on_search(self) -> None:
        """Chạy search mọi keyword × provider × loại media song song."""
        keywords = [line.strip() for line in self.query_edit.toPlainText().splitlines()
                    if line.strip()]
        if not keywords:
            self.window.toast("Nhập ít nhất một từ khóa.")
            return
        selected = [n for n, c in self.provider_checks.items() if c.isChecked()]
        if not selected:
            self.window.toast("Chọn ít nhất một nguồn.")
            return

        self.search_btn.setEnabled(False)
        self.search_btn.setText("Đang tìm...")
        self.grid.clear()
        self._results = []
        try:
            tasks: list[tuple[str, str, asyncio.Task]] = []
            for keyword in keywords:
                for media_type in self._selected_media_types():
                    for name in selected:
                        provider = self.window.providers[name]
                        if media_type not in provider.supported_types:
                            continue
                        tasks.append((
                            keyword,
                            name,
                            asyncio.ensure_future(
                                provider.search(keyword, media_type, per_page=30)
                            ),
                        ))
            thumb_jobs: list[tuple[int, str]] = []
            for keyword, name, task in tasks:
                try:
                    results = await task
                except Exception as exc:
                    logger.error("Search {} '{}' lỗi: {}", name, keyword, exc)
                    self.window.toast(f"Lỗi khi tìm trên {name}: {exc}")
                    continue
                for result in results:
                    if not self._passes_min_res(result):
                        continue
                    row = self.grid.count()
                    size = (
                        f"{result.width}×{result.height}"
                        if result.width and result.height
                        else ""
                    )
                    dur = f" · {result.duration_sec:.0f}s" if result.duration_sec else ""
                    label = f"[{result.provider}] {result.title[:40]}\n{size}{dur}"
                    self.grid.add_card(label, (result, keyword))
                    self._results.append((result, keyword))
                    thumb_jobs.append((row, result.thumbnail_url))
            self.count_label.setText(
                f"{self.grid.count()} kết quả — tick chọn rồi thêm vào hàng đợi."
            )
            self.window.thumb_loader.fetch_many(thumb_jobs)
        finally:
            self.search_btn.setEnabled(True)
            self.search_btn.setText("🔍 Tìm kiếm")

    def on_add_to_queue(self) -> None:
        """Thêm các item được tick vào DownloadManager."""
        payloads = self.grid.checked_payloads()
        if not payloads:
            self.window.toast("Chưa tick chọn kết quả nào.")
            return
        project = self.project_edit.text().strip() or "default"
        for result, keyword in payloads:
            self.window.manager.add(result, keyword=keyword, project=project)
        self.window.jobs_changed()
        self.window.toast(f"Đã thêm {len(payloads)} mục vào hàng đợi (project '{project}').")

    @asyncSlot()
    async def on_download_url(self) -> None:
        """Dán URL bất kỳ → resolve metadata qua yt-dlp → thêm vào queue."""
        url = self.url_edit.text().strip()
        if not url:
            self.window.toast("Dán URL video vào ô trước đã.")
            return
        ytdlp = self.window.providers.get("ytdlp")
        if ytdlp is None:
            self.window.toast("Provider ytdlp chưa khả dụng.")
            return
        clip = self.clip_edit.text().strip() or None
        self.url_btn.setEnabled(False)
        self.url_btn.setText("Đang lấy metadata...")
        try:
            result = await ytdlp.resolve_url(url, clip=clip)
        except ValueError as exc:  # sai định dạng clip
            self.window.toast(str(exc))
            return
        except Exception as exc:
            logger.error("resolve_url {} lỗi: {}", url, exc)
            self.window.toast(f"Không lấy được metadata: {exc}")
            return
        finally:
            self.url_btn.setEnabled(True)
            self.url_btn.setText("Tải URL này")
        project = self.project_edit.text().strip() or "default"
        from urllib.parse import urlparse

        keyword = urlparse(url).netloc.removeprefix("www.") or "direct-url"
        self.window.manager.add(result, keyword=keyword, project=project)
        self.window.jobs_changed()
        self.window.toast(f"Đã thêm '{result.title[:50]}' vào hàng đợi.")
        self.url_edit.clear()
