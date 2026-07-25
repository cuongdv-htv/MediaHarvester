"""Tab Search: keywords nhiều dòng, chọn providers, grid thumbnail, thêm vào queue.

- Mỗi dòng trong ô query = 1 keyword; search chạy song song mọi keyword × provider.
- Ô dán URL trực tiếp (YouTube/TikTok/X...) → route sang yt-dlp provider.
- Không block UI: mọi I/O qua qasync (@asyncSlot), thumbnail lazy-load có cache.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from mediaharvester.gui.widgets.result_grid import ITEM_DATA_ROLE, ResultGrid
from mediaharvester.providers.base import (
    MediaType,
    Orientation,
    SearchResult,
    passes_orientation,
)

if TYPE_CHECKING:
    from mediaharvester.gui.main_window import MainWindow


@dataclass(frozen=True)
class BatchEntry:
    """Một mục tìm kiếm hàng loạt — snapshot bất biến của project + từ khóa + tùy chọn.

    Chụp lại toàn bộ tùy chọn ngay lúc người dùng bấm "Thêm vào danh sách" để khi
    chạy hàng loạt tái hiện y hệt (mỗi project có thể khác cấu hình).
    """

    project: str
    keywords: tuple[str, ...]
    providers: tuple[str, ...]
    media_types: tuple[MediaType, ...]
    per_page: int
    min_height: int
    orientation: Orientation

    def summary(self) -> str:
        """Dòng mô tả ngắn hiển thị trong danh sách batch."""
        types = "+".join("Ảnh" if t == MediaType.IMAGE else "Video" for t in self.media_types)
        res = f"≥{self.min_height}p" if self.min_height else "mọi độ p.giải"
        return (
            f"{self.project} · {len(self.keywords)} từ khóa · "
            f"{','.join(self.providers)} · {types} · {res} · ≤{self.per_page}"
        )

_MIN_RES_OPTIONS = [
    ("Mọi độ phân giải", 0),
    ("≥ 720p (1280×720)", 720),
    ("≥ 1080p (1920×1080)", 1080),
    ("≥ 4K (3840×2160)", 2160),
]

_ORIENTATION_OPTIONS = [
    ("Mọi hướng", Orientation.ANY),
    ("Ngang (landscape)", Orientation.LANDSCAPE),
    ("Dọc (portrait)", Orientation.PORTRAIT),
    ("Vuông (square)", Orientation.SQUARE),
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
        self.url_edit.setPlaceholderText(
            "Hoặc dán URL: video (YouTube/TikTok/X...) hoặc trang web bất kỳ"
        )
        self.clip_edit = QLineEdit()
        self.clip_edit.setPlaceholderText("Cắt đoạn hh:mm:ss-hh:mm:ss (tùy chọn)")
        self.clip_edit.setFixedWidth(220)
        self.url_btn = QPushButton("Tải URL này")
        self.scrape_btn = QPushButton("🔎 Quét trang")
        self.script_btn = QPushButton("📝 Kịch bản → từ khóa")
        url_row.addWidget(self.url_edit)
        url_row.addWidget(self.clip_edit)
        url_row.addWidget(self.url_btn)
        url_row.addWidget(self.scrape_btn)
        url_row.addWidget(self.script_btn)
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

        self.orientation_combo = QComboBox()
        for label, _ in _ORIENTATION_OPTIONS:
            self.orientation_combo.addItem(label)
        options.addWidget(QLabel("Hướng khung hình:"))
        options.addWidget(self.orientation_combo)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 200)
        self.limit_spin.setValue(30)
        self.limit_spin.setSingleStep(10)
        options.addWidget(QLabel("Số kết quả mỗi nguồn:"))
        options.addWidget(self.limit_spin)

        options.addWidget(QLabel("Project:"))
        self.project_edit = QLineEdit("default")
        options.addWidget(self.project_edit)

        self.search_btn = QPushButton("🔍 Tìm kiếm")
        self.search_btn.setDefault(True)
        options.addWidget(self.search_btn)
        options.addStretch()
        top.addLayout(options, stretch=1)
        root.addLayout(top)

        # ---------- Tìm kiếm hàng loạt ----------
        batch_box = QGroupBox("Tìm kiếm hàng loạt (nhiều project)")
        batch_layout = QHBoxLayout(batch_box)
        self.batch_list = QListWidget()
        self.batch_list.setFixedHeight(90)
        self.batch_list.setToolTip(
            "Mỗi dòng = 1 project + bộ từ khóa + tùy chọn đã chụp lúc thêm. "
            "Bấm 'Chạy tất cả' để tự search và thêm hết kết quả vào hàng đợi."
        )
        batch_layout.addWidget(self.batch_list, stretch=1)
        batch_btns = QVBoxLayout()
        self.batch_add_btn = QPushButton("➕ Thêm project hiện tại")
        self.batch_remove_btn = QPushButton("🗑 Xóa mục chọn")
        self.batch_clear_btn = QPushButton("🧹 Xóa hết")
        self.batch_run_btn = QPushButton("🚀 Chạy tất cả")
        for b in (self.batch_add_btn, self.batch_remove_btn, self.batch_clear_btn,
                  self.batch_run_btn):
            batch_btns.addWidget(b)
        batch_layout.addLayout(batch_btns)
        root.addWidget(batch_box)

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
        self.scrape_btn.clicked.connect(self.on_scrape_page)
        self.script_btn.clicked.connect(self.on_script_to_keywords)
        self.check_all_btn.clicked.connect(lambda: self.grid.set_all_checked(True))
        self.uncheck_all_btn.clicked.connect(lambda: self.grid.set_all_checked(False))
        self.add_queue_btn.clicked.connect(self.on_add_to_queue)
        self.batch_add_btn.clicked.connect(self.on_add_to_batch)
        self.batch_remove_btn.clicked.connect(self._remove_selected_batch)
        self.batch_clear_btn.clicked.connect(self._clear_batch)
        self.batch_run_btn.clicked.connect(self.on_run_batch)
        self.window.thumb_loader.thumb_ready.connect(self.grid.set_thumb)
        self._update_batch_run_label()

    # ---------- Hành vi ----------

    def _selected_media_types(self) -> list[MediaType]:
        if self.radio_image.isChecked():
            return [MediaType.IMAGE]
        if self.radio_video.isChecked():
            return [MediaType.VIDEO]
        return [MediaType.IMAGE, MediaType.VIDEO]

    @staticmethod
    def _passes_min_res(result: SearchResult, min_height: int) -> bool:
        if min_height == 0 or result.height is None:
            return True  # không rõ resolution thì vẫn hiển thị
        return result.height >= min_height or (result.width or 0) >= min_height * 16 // 9

    def _current_keywords(self) -> list[str]:
        return [
            line.strip()
            for line in self.query_edit.toPlainText().splitlines()
            if line.strip()
        ]

    def _selected_providers(self) -> list[str]:
        return [n for n, c in self.provider_checks.items() if c.isChecked()]

    def _current_min_height(self) -> int:
        return _MIN_RES_OPTIONS[self.min_res_combo.currentIndex()][1]

    def _current_orientation(self) -> Orientation:
        return _ORIENTATION_OPTIONS[self.orientation_combo.currentIndex()][1]

    async def _collect_results(
        self,
        keywords: list[str],
        providers: list[str],
        media_types: list[MediaType],
        per_page: int,
        min_height: int,
        orientation: Orientation,
    ) -> list[tuple[SearchResult, str]]:
        """Search song song keyword × provider × loại, áp lọc, trả về (result, keyword).

        Dùng chung cho search thủ công (đổ grid) và chạy hàng loạt (tự thêm queue).
        Lỗi 1 provider được log + toast rồi bỏ qua, không làm hỏng cả lượt.
        """
        tasks: list[tuple[str, str, asyncio.Task]] = []
        for keyword in keywords:
            for media_type in media_types:
                for name in providers:
                    provider = self.window.providers.get(name)
                    if provider is None or media_type not in provider.supported_types:
                        continue
                    tasks.append((
                        keyword,
                        name,
                        asyncio.ensure_future(
                            provider.search(keyword, media_type, per_page=per_page)
                        ),
                    ))
        collected: list[tuple[SearchResult, str]] = []
        for keyword, name, task in tasks:
            try:
                results = await task
            except Exception as exc:
                logger.error("Search {} '{}' lỗi: {}", name, keyword, exc)
                self.window.toast(f"Lỗi khi tìm trên {name}: {exc}")
                continue
            for result in results:
                if not self._passes_min_res(result, min_height):
                    continue
                if not passes_orientation(result.width, result.height, orientation):
                    continue
                collected.append((result, keyword))
        return collected

    @asyncSlot()
    async def on_search(self) -> None:
        """Chạy search mọi keyword × provider × loại media rồi đổ vào lưới thumbnail."""
        keywords = self._current_keywords()
        if not keywords:
            self.window.toast("Nhập ít nhất một từ khóa.")
            return
        selected = self._selected_providers()
        if not selected:
            self.window.toast("Chọn ít nhất một nguồn.")
            return

        self.search_btn.setEnabled(False)
        self.search_btn.setText("Đang tìm...")
        self.grid.clear()
        self._results = []
        try:
            results = await self._collect_results(
                keywords,
                selected,
                self._selected_media_types(),
                self.limit_spin.value(),
                self._current_min_height(),
                self._current_orientation(),
            )
            thumb_jobs: list[tuple[int, str]] = []
            for result, keyword in results:
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

    # ---------- Tìm kiếm hàng loạt ----------

    def on_add_to_batch(self) -> None:
        """Chụp project + từ khóa + tùy chọn hiện tại thành 1 mục trong danh sách batch."""
        keywords = self._current_keywords()
        if not keywords:
            self.window.toast("Nhập ít nhất một từ khóa trước khi thêm vào danh sách.")
            return
        providers = self._selected_providers()
        if not providers:
            self.window.toast("Chọn ít nhất một nguồn.")
            return
        entry = BatchEntry(
            project=self.project_edit.text().strip() or "default",
            keywords=tuple(keywords),
            providers=tuple(providers),
            media_types=tuple(self._selected_media_types()),
            per_page=self.limit_spin.value(),
            min_height=self._current_min_height(),
            orientation=self._current_orientation(),
        )
        item = self.batch_list.count()
        self.batch_list.addItem(entry.summary())
        self.batch_list.item(item).setData(ITEM_DATA_ROLE, entry)
        self.query_edit.clear()  # dọn ô để gõ mục kế
        self._update_batch_run_label()
        self.window.toast(f"Đã thêm vào danh sách: {entry.summary()}")

    def _batch_entries(self) -> list[BatchEntry]:
        return [
            self.batch_list.item(i).data(ITEM_DATA_ROLE)
            for i in range(self.batch_list.count())
        ]

    def _remove_selected_batch(self) -> None:
        for item in self.batch_list.selectedItems():
            self.batch_list.takeItem(self.batch_list.row(item))
        self._update_batch_run_label()

    def _clear_batch(self) -> None:
        self.batch_list.clear()
        self._update_batch_run_label()

    def _update_batch_run_label(self) -> None:
        n = self.batch_list.count()
        self.batch_run_btn.setText(f"🚀 Chạy tất cả ({n})" if n else "🚀 Chạy tất cả")
        self.batch_run_btn.setEnabled(n > 0)

    @asyncSlot()
    async def on_run_batch(self) -> None:
        """Xác nhận rồi chạy toàn bộ danh sách batch: search từng mục + tự thêm queue."""
        entries = self._batch_entries()
        if not entries:
            self.window.toast("Danh sách hàng loạt đang trống.")
            return
        confirm = QMessageBox.question(
            self,
            "Chạy tìm kiếm hàng loạt",
            f"Sẽ tìm {len(entries)} project và thêm TOÀN BỘ kết quả vào hàng đợi tải.\n"
            "Tiếp tục?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.batch_run_btn.setEnabled(False)
        try:
            added, n_projects = await self._run_batch(entries)
        finally:
            self._update_batch_run_label()

        self.window.jobs_changed()
        self._clear_batch()
        self.window.toast(
            f"Hàng loạt xong: đã thêm {added} mục từ {n_projects} project vào hàng đợi."
        )

    async def _run_batch(self, entries: list[BatchEntry]) -> tuple[int, int]:
        """Chạy tuần tự từng entry, tự thêm mọi kết quả vào queue. Trả về (tổng mục, số project)."""
        total_added = 0
        for i, entry in enumerate(entries, start=1):
            self.count_label.setText(
                f"Đang chạy hàng loạt: project {i}/{len(entries)} — '{entry.project}'..."
            )
            results = await self._collect_results(
                list(entry.keywords),
                list(entry.providers),
                list(entry.media_types),
                entry.per_page,
                entry.min_height,
                entry.orientation,
            )
            for result, keyword in results:
                self.window.manager.add(result, keyword=keyword, project=entry.project)
            total_added += len(results)
            self.count_label.setText(
                f"Hàng loạt: project {i}/{len(entries)} '{entry.project}' — "
                f"thêm {len(results)} mục (tổng {total_added})."
            )
        return total_added, len(entries)

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

    @asyncSlot()
    async def on_scrape_page(self) -> None:
        """Quét URL trang bất kỳ → liệt kê ảnh/video vào grid để tick chọn."""
        url = self.url_edit.text().strip()
        if not url:
            self.window.toast("Dán URL trang web vào ô trước đã.")
            return
        scraper = self.window.providers.get("scraper")
        if scraper is None:
            self.window.toast("Provider scraper chưa khả dụng.")
            return
        self.scrape_btn.setEnabled(False)
        self.scrape_btn.setText("Đang quét...")
        try:
            results = await scraper.scrape(url)
        except ValueError as exc:  # robots.txt không cho phép
            self.window.toast(str(exc).splitlines()[0])
            return
        except Exception as exc:
            logger.error("Quét trang {} lỗi: {}", url, exc)
            self.window.toast(f"Không quét được trang: {exc}")
            return
        finally:
            self.scrape_btn.setEnabled(True)
            self.scrape_btn.setText("🔎 Quét trang")

        from urllib.parse import urlparse as _urlparse

        keyword = _urlparse(url).netloc.removeprefix("www.") or "scraped"
        self.grid.clear()
        self._results = []
        thumb_jobs: list[tuple[int, str]] = []
        for result in results:
            row = self.grid.count()
            label = f"[{result.media_type}] {result.title[:40]}"
            self.grid.add_card(label, (result, keyword))
            self._results.append((result, keyword))
            if result.thumbnail_url:
                thumb_jobs.append((row, result.thumbnail_url))
        self.count_label.setText(
            f"Quét được {len(results)} media từ {keyword} — tick chọn rồi thêm vào hàng đợi."
        )
        self.window.thumb_loader.fetch_many(thumb_jobs)

    def on_script_to_keywords(self) -> None:
        """Mở dialog paste kịch bản → tách từ khóa → đổ vào ô query."""
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QPlainTextEdit,
            QVBoxLayout,
        )

        from mediaharvester.utils.keywords import HeuristicKeywordExtractor

        dialog = QDialog(self)
        dialog.setWindowTitle("Kịch bản → từ khóa")
        dialog.resize(640, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Dán kịch bản video (tiếng Việt hoặc tiếng Anh):"))
        editor = QPlainTextEdit()
        layout.addWidget(editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Tách từ khóa")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        text = editor.toPlainText().strip()
        if not text:
            return
        keywords = HeuristicKeywordExtractor().extract(text, max_keywords=12)
        if not keywords:
            self.window.toast("Không tách được từ khóa nào từ văn bản này.")
            return
        self.query_edit.setPlainText("\n".join(keywords))
        self.window.toast(f"Đã tách {len(keywords)} từ khóa — bấm Tìm kiếm để chạy.")
