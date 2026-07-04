"""Tab Settings: API keys (.env), thư mục thư viện, concurrent, quality,
cookies browser, update yt-dlp, health-check providers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from mediaharvester.core.config import ApiKeys, save_api_keys, save_config

if TYPE_CHECKING:
    from mediaharvester.gui.main_window import MainWindow

_QUALITIES = ["720p", "1080p", "1440p", "2160p"]
_COOKIE_OPTIONS = ["Không dùng", "chrome", "edge", "firefox"]


class SettingsTab(QWidget):
    """Tab cấu hình ứng dụng."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window = window
        config = window.config
        keys = window.api_keys

        root = QVBoxLayout(self)

        # ---------- API keys ----------
        key_box = QGroupBox("API keys (lưu vào .env — không bao giờ nằm trong code/DB)")
        key_form = QFormLayout(key_box)
        self.pexels_edit = QLineEdit(keys.pexels_api_key)
        self.pixabay_edit = QLineEdit(keys.pixabay_api_key)
        self.unsplash_edit = QLineEdit(keys.unsplash_access_key)
        for edit in (self.pexels_edit, self.pixabay_edit, self.unsplash_edit):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_form.addRow("Pexels:", self.pexels_edit)
        key_form.addRow("Pixabay:", self.pixabay_edit)
        key_form.addRow("Unsplash:", self.unsplash_edit)
        self.show_keys_btn = QPushButton("👁 Hiện/ẩn keys")
        self.show_keys_btn.setCheckable(True)
        key_form.addRow("", self.show_keys_btn)
        root.addWidget(key_box)

        # ---------- Cấu hình chung ----------
        general_box = QGroupBox("Cấu hình chung (config.toml)")
        form = QFormLayout(general_box)
        lib_row = QHBoxLayout()
        self.library_edit = QLineEdit(str(config.library_root))
        self.browse_btn = QPushButton("Chọn...")
        lib_row.addWidget(self.library_edit)
        lib_row.addWidget(self.browse_btn)
        form.addRow("Thư mục thư viện:", lib_row)

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(config.download.max_concurrent)
        form.addRow("Số download song song:", self.concurrent_spin)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(_QUALITIES)
        self.quality_combo.setCurrentText(config.default_quality)
        form.addRow("Chất lượng video mặc định:", self.quality_combo)

        self.cookies_combo = QComboBox()
        self.cookies_combo.addItems(_COOKIE_OPTIONS)
        if config.ytdlp.cookies_from_browser in _COOKIE_OPTIONS:
            self.cookies_combo.setCurrentText(config.ytdlp.cookies_from_browser)
        form.addRow("Cookies từ browser (yt-dlp):", self.cookies_combo)
        root.addWidget(general_box)

        # ---------- Nút hành động ----------
        actions = QHBoxLayout()
        self.save_btn = QPushButton("💾 Lưu cấu hình")
        self.update_ytdlp_btn = QPushButton("⬆ Update yt-dlp.exe")
        self.health_btn = QPushButton("🩺 Health-check providers")
        actions.addWidget(self.save_btn)
        actions.addWidget(self.update_ytdlp_btn)
        actions.addWidget(self.health_btn)
        actions.addStretch()
        root.addLayout(actions)
        root.addStretch()

        self.show_keys_btn.toggled.connect(self._toggle_keys)
        self.browse_btn.clicked.connect(self._browse_library)
        self.save_btn.clicked.connect(self._save)
        self.update_ytdlp_btn.clicked.connect(self._update_ytdlp)
        self.health_btn.clicked.connect(self._health_check)

    # ---------- Hành vi ----------

    def _toggle_keys(self, show: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        for edit in (self.pexels_edit, self.pixabay_edit, self.unsplash_edit):
            edit.setEchoMode(mode)

    def _browse_library(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục thư viện")
        if folder:
            self.library_edit.setText(folder)

    def _save(self) -> None:
        """Ghi .env + config.toml. Một số thay đổi cần khởi động lại app."""
        keys = ApiKeys(
            pexels_api_key=self.pexels_edit.text().strip(),
            pixabay_api_key=self.pixabay_edit.text().strip(),
            unsplash_access_key=self.unsplash_edit.text().strip(),
        )
        config = self.window.config
        config.library_root = Path(self.library_edit.text().strip() or "library")
        config.download.max_concurrent = self.concurrent_spin.value()
        config.default_quality = self.quality_combo.currentText()
        cookies = self.cookies_combo.currentText()
        config.ytdlp.cookies_from_browser = None if cookies == "Không dùng" else cookies
        try:
            save_api_keys(keys)
            save_config(config)
        except OSError as exc:
            logger.error("Lưu cấu hình lỗi: {}", exc)
            self.window.toast(f"Không lưu được cấu hình: {exc}")
            return
        self.window.api_keys = keys
        self.window.toast(
            "Đã lưu. Thay đổi thư mục thư viện / số luồng cần khởi động lại app để áp dụng."
        )

    @asyncSlot()
    async def _update_ytdlp(self) -> None:
        """Chạy vendor/yt-dlp.exe -U (ngoại lệ subprocess duy nhất được phép)."""
        exe = Path("vendor") / "yt-dlp.exe"
        if not exe.exists():
            self.window.toast("Chưa có vendor/yt-dlp.exe — chạy scripts/fetch_vendor.py trước.")
            return
        self.update_ytdlp_btn.setEnabled(False)
        self.update_ytdlp_btn.setText("Đang update...")
        try:
            proc = await asyncio.create_subprocess_exec(
                str(exe), "-U",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
            last_line = out.decode(errors="replace").strip().splitlines()[-1:]
            self.window.toast(f"yt-dlp: {last_line[0] if last_line else 'xong'}")
        except (OSError, TimeoutError) as exc:
            logger.error("Update yt-dlp lỗi: {}", exc)
            self.window.toast(f"Update yt-dlp lỗi: {exc}")
        finally:
            self.update_ytdlp_btn.setEnabled(True)
            self.update_ytdlp_btn.setText("⬆ Update yt-dlp.exe")

    @asyncSlot()
    async def _health_check(self) -> None:
        """Kiểm tra key/kết nối của tất cả providers song song."""
        self.health_btn.setEnabled(False)
        self.health_btn.setText("Đang kiểm tra...")
        try:
            names = list(self.window.providers)
            checks = await asyncio.gather(
                *(self.window.providers[n].health_check() for n in names),
                return_exceptions=True,
            )
            lines = []
            for name, ok in zip(names, checks, strict=True):
                if isinstance(ok, BaseException):
                    lines.append(f"✘ {name}: {ok}")
                else:
                    lines.append(f"{'✔' if ok else '✘'} {name}")
            QMessageBox.information(self, "Health-check providers", "\n".join(lines))
        finally:
            self.health_btn.setEnabled(True)
            self.health_btn.setText("🩺 Health-check providers")
