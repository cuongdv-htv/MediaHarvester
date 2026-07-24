"""Tab Library: duyệt asset theo project/provider/loại, tìm text, export CSV nguồn."""

from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlmodel import select

from mediaharvester.core.database import get_session
from mediaharvester.core.models import Asset, Project
from mediaharvester.gui.widgets.result_grid import ITEM_DATA_ROLE, ResultGrid

if TYPE_CHECKING:
    from mediaharvester.gui.main_window import MainWindow


class LibraryTab(QWidget):
    """Tab thư viện asset đã tải."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window = window

        root = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.project_combo = QComboBox()
        self.provider_combo = QComboBox()
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Tất cả loại", "Ảnh", "Video"])
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Tìm theo tiêu đề/từ khóa...")
        self.refresh_btn = QPushButton("🔄 Làm mới")
        self.export_btn = QPushButton("📄 Export danh sách nguồn (CSV)")
        filters.addWidget(QLabel("Project:"))
        filters.addWidget(self.project_combo)
        filters.addWidget(QLabel("Nguồn:"))
        filters.addWidget(self.provider_combo)
        filters.addWidget(self.type_combo)
        filters.addWidget(self.search_edit, stretch=1)
        filters.addWidget(self.refresh_btn)
        filters.addWidget(self.export_btn)
        root.addLayout(filters)

        self.count_label = QLabel("")
        root.addWidget(self.count_label)

        self.grid = ResultGrid(checkable=False)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        root.addWidget(self.grid, stretch=1)

        self.refresh_btn.clicked.connect(self.reload_and_refresh)
        self.export_btn.clicked.connect(self.export_csv)
        self.search_edit.returnPressed.connect(self.refresh)
        self.project_combo.currentIndexChanged.connect(lambda _: self.refresh())
        self.provider_combo.currentIndexChanged.connect(lambda _: self.refresh())
        self.type_combo.currentIndexChanged.connect(lambda _: self.refresh())
        self.grid.itemDoubleClicked.connect(self._open_file)
        self.grid.customContextMenuRequested.connect(self._context_menu)

        # Refresh gộp (throttle) khi có download xong liên tiếp
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(1500)
        self._refresh_timer.timeout.connect(self.reload_and_refresh)

        self._loading_filters = False
        self.reload_and_refresh()

    # ---------- Dữ liệu ----------

    def schedule_refresh(self) -> None:
        """Gọi khi có asset mới — refresh sau 1.5s (gộp nhiều lần thành một)."""
        self._refresh_timer.start()

    @staticmethod
    def _restore_choice(combo: QComboBox, text: str) -> None:
        """Chọn lại mục cũ nếu vẫn còn trong danh sách (không còn thì về 'Tất cả')."""
        if not text:
            return
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def reload_filters(self) -> None:
        """Nạp danh sách project/provider vào combo lọc, giữ nguyên lựa chọn hiện tại.

        Cần gọi lại sau khi tải xong vì project/nguồn mới chỉ xuất hiện trong DB
        tại thời điểm job được thêm vào hàng đợi.
        """
        self._loading_filters = True
        try:
            with get_session(self.window.engine) as session:
                projects = session.exec(select(Project.name)).all()
                providers = session.exec(select(Asset.provider).distinct()).all()
            prev_project = self.project_combo.currentText()
            prev_provider = self.provider_combo.currentText()
            self.project_combo.clear()
            self.project_combo.addItem("Tất cả project")
            self.project_combo.addItems(list(projects))
            self.provider_combo.clear()
            self.provider_combo.addItem("Tất cả nguồn")
            self.provider_combo.addItems(sorted(providers))
            self._restore_choice(self.project_combo, prev_project)
            self._restore_choice(self.provider_combo, prev_provider)
        finally:
            self._loading_filters = False

    def reload_and_refresh(self) -> None:
        """Nạp lại bộ lọc (bắt project/nguồn mới) rồi vẽ lại lưới asset."""
        self.reload_filters()
        self.refresh()

    def refresh(self) -> None:
        """Query DB theo bộ lọc và đổ vào grid thumbnail."""
        if self._loading_filters:
            return
        with get_session(self.window.engine) as session:
            query = select(Asset).order_by(Asset.created_at.desc())  # type: ignore[attr-defined]
            if self.project_combo.currentIndex() > 0:
                project = session.exec(
                    select(Project).where(Project.name == self.project_combo.currentText())
                ).first()
                if project is not None:
                    query = query.where(Asset.project_id == project.id)
            if self.provider_combo.currentIndex() > 0:
                query = query.where(Asset.provider == self.provider_combo.currentText())
            if self.type_combo.currentIndex() == 1:
                query = query.where(Asset.media_type == "image")
            elif self.type_combo.currentIndex() == 2:
                query = query.where(Asset.media_type == "video")
            text = self.search_edit.text().strip().lower()
            assets = session.exec(query.limit(500)).all()
        if text:
            assets = [
                a for a in assets
                if text in a.title.lower() or text in a.keywords.lower()
            ]

        self.grid.clear()
        thumb_dir = self.window.config.library_root / ".thumbnails"
        for asset in assets:
            file_path = Path(asset.file_path)
            label = f"[{asset.provider}] {asset.title[:40]}"
            item = self.grid.add_card(label, asset)
            thumb = thumb_dir / f"{file_path.stem}.jpg"
            if thumb.exists():
                self.grid.set_thumb(self.grid.count() - 1, str(thumb))
            item.setToolTip(
                f"{asset.title}\n{asset.provider} · {asset.license}\n"
                f"Tác giả: {asset.author or '?'}\n{asset.file_path}"
            )
        self.count_label.setText(f"{len(assets)} asset trong thư viện.")

    # ---------- Hành động ----------

    def _asset_at(self, pos) -> Asset | None:
        item = self.grid.itemAt(pos)
        return item.data(ITEM_DATA_ROLE) if item is not None else None

    def _open_file(self, item) -> None:
        asset: Asset = item.data(ITEM_DATA_ROLE)
        path = Path(asset.file_path)
        if path.exists():
            os.startfile(path)  # noqa: S606 — mở file bằng app mặc định Windows
        else:
            self.window.toast(f"File không còn tồn tại: {path}")

    def _context_menu(self, pos) -> None:
        asset = self._asset_at(pos)
        if asset is None:
            return
        menu = QMenu(self)
        open_dir = menu.addAction("📂 Mở thư mục chứa file")
        copy_path = menu.addAction("📋 Copy đường dẫn")
        show_meta = menu.addAction("ℹ Xem metadata")
        menu.addSeparator()
        delete = menu.addAction("🗑 Xóa asset")
        chosen = menu.exec(self.grid.viewport().mapToGlobal(pos))
        if chosen == open_dir:
            subprocess.run(["explorer", "/select,", str(Path(asset.file_path))])  # noqa: S603,S607
        elif chosen == copy_path:
            QApplication.clipboard().setText(asset.file_path)
            self.window.toast("Đã copy đường dẫn.")
        elif chosen == show_meta:
            self._show_metadata(asset)
        elif chosen == delete:
            self._delete_asset(asset)

    def _show_metadata(self, asset: Asset) -> None:
        sidecar = Path(asset.file_path + ".meta.json")
        if sidecar.exists():
            content = sidecar.read_text(encoding="utf-8")
        else:
            content = json.dumps(asset.model_dump(), ensure_ascii=False, indent=2, default=str)
        box = QMessageBox(self)
        box.setWindowTitle(f"Metadata — {asset.title[:60]}")
        box.setText(content[:3000])
        box.exec()

    def _delete_asset(self, asset: Asset) -> None:
        confirm = QMessageBox.question(
            self,
            "Xóa asset",
            f"Xóa file và record khỏi thư viện?\n\n{asset.file_path}",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            path = Path(asset.file_path)
            path.unlink(missing_ok=True)
            Path(asset.file_path + ".meta.json").unlink(missing_ok=True)
            thumb = self.window.config.library_root / ".thumbnails" / f"{path.stem}.jpg"
            thumb.unlink(missing_ok=True)
            with get_session(self.window.engine) as session:
                db_asset = session.get(Asset, asset.id)
                if db_asset is not None:
                    session.delete(db_asset)
                    session.commit()
            self.window.toast(f"Đã xóa: {path.name}")
            self.refresh()
        except OSError as exc:
            logger.error("Xóa asset lỗi: {}", exc)
            self.window.toast(f"Không xóa được: {exc}")

    def export_csv(self) -> None:
        """Xuất danh sách nguồn (phục vụ ghi credit) ra CSV."""
        dest, _ = QFileDialog.getSaveFileName(
            self, "Lưu danh sách nguồn", "danh-sach-nguon.csv", "CSV (*.csv)"
        )
        if not dest:
            return
        with get_session(self.window.engine) as session:
            assets = session.exec(select(Asset)).all()
        try:
            with open(dest, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["provider", "title", "author", "license", "source_page_url", "file_path"]
                )
                for a in assets:
                    writer.writerow(
                        [a.provider, a.title, a.author or "", a.license,
                         a.source_page_url, a.file_path]
                    )
            self.window.toast(f"Đã xuất {len(assets)} dòng ra {dest}")
        except OSError as exc:
            logger.error("Export CSV lỗi: {}", exc)
            self.window.toast(f"Không ghi được CSV: {exc}")
