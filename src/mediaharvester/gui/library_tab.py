"""Tab Library: duyệt asset theo project/provider/loại, tìm text, export CSV nguồn."""

from __future__ import annotations

import asyncio
import csv
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot
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
        filters.addWidget(QLabel("Project:"))
        filters.addWidget(self.project_combo)
        filters.addWidget(QLabel("Nguồn:"))
        filters.addWidget(self.provider_combo)
        filters.addWidget(self.type_combo)
        filters.addWidget(self.search_edit, stretch=1)
        filters.addWidget(self.refresh_btn)
        root.addLayout(filters)

        actions = QHBoxLayout()
        self.export_btn = QPushButton("📄 Export danh sách nguồn (CSV)")
        self.download_project_btn = QPushButton()
        self.delete_project_btn = QPushButton("🗑 Xóa project đang chọn")
        self.delete_all_btn = QPushButton("🗑 Xóa toàn bộ project...")
        self.delete_all_btn.setToolTip(
            "Xóa nhiều project cùng lúc — hộp thoại cho tích chọn project cần giữ lại."
        )
        actions.addWidget(self.export_btn)
        actions.addWidget(self.download_project_btn)
        actions.addWidget(self.delete_project_btn)
        actions.addWidget(self.delete_all_btn)
        actions.addStretch()
        root.addLayout(actions)

        self.count_label = QLabel("")
        root.addWidget(self.count_label)

        self.grid = ResultGrid(checkable=False)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        root.addWidget(self.grid, stretch=1)

        self.refresh_btn.clicked.connect(self.reload_and_refresh)
        self.export_btn.clicked.connect(self.export_csv)
        self.download_project_btn.clicked.connect(self.download_project)
        self.delete_project_btn.clicked.connect(self.delete_project)
        self.delete_all_btn.clicked.connect(self.delete_all_projects)
        self.search_edit.returnPressed.connect(self.refresh)
        self.project_combo.currentIndexChanged.connect(lambda _: self.refresh())
        self.project_combo.currentIndexChanged.connect(lambda _: self._update_download_btn())
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
        self._update_download_btn()
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

    # ---------- Thao tác theo project ----------

    def _selected_project(self) -> str | None:
        """Tên project đang chọn; None nếu đang để 'Tất cả project'."""
        if self.project_combo.currentIndex() <= 0:
            return None
        return self.project_combo.currentText()

    def _project_assets(self, project: str) -> list[Asset]:
        """Toàn bộ asset thuộc 1 project (rỗng nếu project không còn)."""
        with get_session(self.window.engine) as session:
            row = session.exec(select(Project).where(Project.name == project)).first()
            if row is None:
                return []
            return list(session.exec(select(Asset).where(Asset.project_id == row.id)).all())

    def _all_assets(self) -> list[Asset]:
        """Toàn bộ asset của mọi project trong thư viện."""
        with get_session(self.window.engine) as session:
            return list(session.exec(select(Asset)).all())

    def _update_download_btn(self) -> None:
        """Đổi nhãn nút tải theo lựa chọn ở dropdown để rõ sẽ tải phạm vi nào."""
        project = self._selected_project()
        if project is None:
            self.download_project_btn.setText("⬇ Tải toàn bộ thư viện về máy")
            self.download_project_btn.setToolTip(
                "Copy ảnh/video của TẤT CẢ project sang thư mục bạn chỉ định — "
                "mỗi project nằm trong một thư mục con. Giữ nguyên file gốc trong thư viện."
            )
        else:
            self.download_project_btn.setText(f"⬇ Tải project '{project}' về máy")
            self.download_project_btn.setToolTip(
                f"Copy toàn bộ ảnh/video của project '{project}' sang thư mục bạn chỉ định "
                "(giữ nguyên file gốc trong thư viện)."
            )

    @staticmethod
    def _copy_media(
        assets: list[Asset], library_root: Path, dest_root: Path
    ) -> tuple[int, int, int, int]:
        """Copy file ảnh/video sang `dest_root`, giữ cấu trúc thư mục của thư viện.

        Chỉ copy chính file media — không kèm sidecar .meta.json hay thumbnail.
        Trả về (đã copy, đã có sẵn, thiếu file, lỗi).
        """
        lib = library_root.resolve()
        copied = existed = missing = failed = 0
        for asset in assets:
            src = Path(asset.file_path)
            if not src.exists():
                missing += 1
                logger.warning("Bỏ qua (file không còn): {}", src)
                continue
            resolved = src.resolve()
            rel = (
                resolved.relative_to(lib) if resolved.is_relative_to(lib) else Path(src.name)
            )
            target = dest_root / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if target.stat().st_size == resolved.stat().st_size:
                        existed += 1  # đã copy lần trước — bỏ qua, không ghi đè
                        continue
                    # Trùng tên nhưng khác nội dung → thêm hậu tố, tuyệt đối không ghi đè
                    stem, suffix, n = target.stem, target.suffix, 2
                    while target.exists():
                        target = target.with_name(f"{stem}_{n}{suffix}")
                        n += 1
                shutil.copy2(resolved, target)
                copied += 1
            except OSError as exc:
                failed += 1
                logger.error("Copy lỗi {} → {}: {}", src, target, exc)
        return copied, existed, missing, failed

    @asyncSlot()
    async def download_project(self) -> None:
        """Copy ảnh/video ra thư mục người dùng chọn.

        Phạm vi theo dropdown Project: một project cụ thể, hoặc **toàn bộ thư viện**
        khi đang để 'Tất cả project' (mỗi project thành một thư mục con).
        """
        project = self._selected_project()
        if project is None:
            source = self._all_assets()
            scope = "toàn bộ thư viện"
        else:
            source = self._project_assets(project)
            scope = f"project '{project}'"
        assets = [a for a in source if a.media_type in ("image", "video")]
        if not assets:
            self.window.toast(f"Chưa có ảnh/video nào trong {scope}.")
            return
        n_projects = len({a.project_id for a in assets})

        dest = QFileDialog.getExistingDirectory(
            self, f"Chọn thư mục lưu {len(assets)} file của {scope}"
        )
        if not dest:
            return

        label = self.download_project_btn.text()
        self.download_project_btn.setEnabled(False)
        self.download_project_btn.setText("Đang copy...")
        self.window.toast(f"Đang copy {len(assets)} file của {scope}...")
        try:
            copied, existed, missing, failed = await asyncio.to_thread(
                self._copy_media, assets, self.window.config.library_root, Path(dest)
            )
        except OSError as exc:
            logger.error("Tải {} lỗi: {}", scope, exc)
            self.window.toast(f"Không copy được: {exc}")
            return
        finally:
            self.download_project_btn.setEnabled(True)
            self.download_project_btn.setText(label)

        parts = [f"đã copy {copied} file"]
        if existed:
            parts.append(f"{existed} file đã có sẵn")
        if missing:
            parts.append(f"{missing} file không còn trên đĩa")
        if failed:
            parts.append(f"{failed} lỗi")
        summary = f"Xong: {', '.join(parts)}."
        if project is None:
            summary += f"\nTừ {n_projects} project (mỗi project một thư mục con)."
        QMessageBox.information(
            self, f"Tải {scope}", f"{summary}\n\nThư mục đích:\n{dest}"
        )

    @staticmethod
    def _delete_files(assets: list[Asset], thumb_dir: Path, project_dir: Path) -> int:
        """Xóa file media + sidecar + thumbnail của các asset; dọn thư mục rỗng."""
        removed = 0
        for asset in assets:
            path = Path(asset.file_path)
            try:
                if path.exists():
                    path.unlink()
                    removed += 1
                Path(asset.file_path + ".meta.json").unlink(missing_ok=True)
                (thumb_dir / f"{path.stem}.jpg").unlink(missing_ok=True)
            except OSError as exc:
                logger.error("Không xóa được {}: {}", path, exc)
        # Dọn thư mục rỗng còn lại của project (từ trong ra ngoài)
        if project_dir.exists():
            for folder in sorted(
                (p for p in project_dir.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                try:
                    folder.rmdir()
                except OSError:
                    pass  # còn file khác — giữ nguyên
            try:
                project_dir.rmdir()
            except OSError:
                pass
        return removed

    @staticmethod
    def _delete_files_for_projects(
        per_project_assets: dict[str, list[Asset]], thumb_dir: Path, library_root: Path
    ) -> int:
        """Xóa file của nhiều project (dùng lại _delete_files cho từng project)."""
        return sum(
            LibraryTab._delete_files(assets, thumb_dir, library_root / name)
            for name, assets in per_project_assets.items()
        )

    def _remove_projects_from_db(self, names: list[str]) -> int:
        """Xóa record project + asset của nó khỏi DB. Trả về số asset đã gỡ."""
        removed_assets = 0
        with get_session(self.window.engine) as session:
            for name in names:
                row = session.exec(select(Project).where(Project.name == name)).first()
                if row is None:
                    continue
                for asset in session.exec(
                    select(Asset).where(Asset.project_id == row.id)
                ).all():
                    session.delete(asset)
                    removed_assets += 1
                session.delete(row)
            session.commit()
        return removed_assets

    async def _purge_projects(self, names: list[str], delete_files: bool) -> tuple[int, int]:
        """Xóa các project: (tùy chọn) file trên đĩa rồi record DB.

        Trả về (số asset đã gỡ, số file đã xóa trên đĩa).
        """
        per_project_assets = {name: self._project_assets(name) for name in names}
        removed_files = 0
        if delete_files:
            removed_files = await asyncio.to_thread(
                self._delete_files_for_projects,
                per_project_assets,
                self.window.config.library_root / ".thumbnails",
                self.window.config.library_root,
            )
        removed_assets = self._remove_projects_from_db(names)
        return removed_assets, removed_files

    @asyncSlot()
    async def delete_project(self) -> None:
        """Xóa project đang chọn khỏi thư viện; có tùy chọn xóa luôn file trên đĩa."""
        project = self._selected_project()
        if project is None:
            self.window.toast(
                "Hãy chọn một project cụ thể ở ô Project trước (đang là 'Tất cả project')."
            )
            return
        assets = self._project_assets(project)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Xóa project")
        box.setText(f"Xóa project '{project}' khỏi thư viện?")
        box.setInformativeText(
            f"{len(assets)} asset sẽ bị gỡ khỏi thư viện.\n\n"
            "Mặc định file trên đĩa được GIỮ LẠI — tick ô bên dưới nếu muốn xóa hẳn."
        )
        checkbox = QCheckBox("Xóa luôn file trên đĩa (không hoàn tác được)")
        box.setCheckBox(checkbox)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        delete_files = checkbox.isChecked()

        if delete_files:
            self.window.toast(f"Đang xóa file của project '{project}'...")
        try:
            removed_assets, removed_files = await self._purge_projects([project], delete_files)
        except Exception as exc:  # DB/IO lỗi không được làm chết app
            logger.exception("Xóa project lỗi: {}", exc)
            self.window.toast(f"Không xóa được project: {exc}")
            return

        detail = (
            f"đã xóa {removed_files} file trên đĩa"
            if delete_files
            else "file trên đĩa được giữ lại"
        )
        self.window.toast(f"Đã xóa project '{project}' ({removed_assets} asset, {detail}).")
        self.reload_and_refresh()

    @asyncSlot()
    async def delete_all_projects(self) -> None:
        """Xóa nhiều project cùng lúc — hộp thoại cho tích chọn project cần giữ lại."""
        with get_session(self.window.engine) as session:
            names = sorted(session.exec(select(Project.name)).all())
        if not names:
            self.window.toast("Chưa có project nào trong thư viện.")
            return
        counts = {name: len(self._project_assets(name)) for name in names}

        chosen = self._ask_projects_to_delete(names, counts)
        if chosen is None:
            return
        to_delete, delete_files = chosen
        if not to_delete:
            self.window.toast("Không có project nào được chọn để xóa.")
            return

        if delete_files:
            self.window.toast(f"Đang xóa file của {len(to_delete)} project...")
        try:
            removed_assets, removed_files = await self._purge_projects(to_delete, delete_files)
        except Exception as exc:  # DB/IO lỗi không được làm chết app
            logger.exception("Xóa toàn bộ project lỗi: {}", exc)
            self.window.toast(f"Không xóa được: {exc}")
            return

        detail = (
            f"đã xóa {removed_files} file trên đĩa"
            if delete_files
            else "file trên đĩa được giữ lại"
        )
        self.window.toast(
            f"Đã xóa {len(to_delete)} project ({removed_assets} asset, {detail})."
        )
        self.reload_and_refresh()

    def _ask_projects_to_delete(
        self, names: list[str], counts: dict[str, int]
    ) -> tuple[list[str], bool] | None:
        """Hộp thoại tích chọn project để XÓA. None nếu người dùng hủy.

        Mặc định tích sẵn mọi project (sẽ xóa) trừ 'default' (giữ lại). Người dùng
        bỏ tích những project muốn giữ (vd project test).
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Xóa toàn bộ project")
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                "Chọn project muốn <b>XÓA</b> (bỏ tích để giữ lại):"
            )
        )

        checks: dict[str, QCheckBox] = {}
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        for name in names:
            cb = QCheckBox(f"{name}  ({counts.get(name, 0)} asset)")
            cb.setChecked(name != "default")  # giữ 'default' theo mặc định
            checks[name] = cb
            inner_layout.addWidget(cb)
        inner_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMinimumHeight(200)
        layout.addWidget(scroll)

        sel_row = QHBoxLayout()
        all_btn = QPushButton("Chọn tất cả")
        none_btn = QPushButton("Bỏ chọn tất cả")
        all_btn.clicked.connect(lambda: [c.setChecked(True) for c in checks.values()])
        none_btn.clicked.connect(lambda: [c.setChecked(False) for c in checks.values()])
        sel_row.addWidget(all_btn)
        sel_row.addWidget(none_btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        disk_check = QCheckBox("Xóa luôn file trên đĩa (không hoàn tác được)")
        layout.addWidget(disk_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        to_delete = [name for name, cb in checks.items() if cb.isChecked()]
        return to_delete, disk_check.isChecked()

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
