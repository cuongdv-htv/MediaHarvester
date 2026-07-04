"""Tab Queue: bảng jobs với progress bar, tốc độ, pause/cancel, quota API còn lại."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mediaharvester.core.downloader import JobState, JobStatus
from mediaharvester.gui.widgets.progress_delegate import PROGRESS_ROLE, ProgressDelegate

if TYPE_CHECKING:
    from mediaharvester.gui.main_window import MainWindow

_STATUS_VN = {
    JobStatus.QUEUED: "Chờ",
    JobStatus.DOWNLOADING: "Đang tải",
    JobStatus.PROCESSING: "Đang xử lý",
    JobStatus.DONE: "✔ Xong",
    JobStatus.FAILED: "✘ Lỗi",
    JobStatus.SKIPPED_DUPLICATE: "↷ Trùng",
    JobStatus.CANCELLED: "Đã hủy",
}

_COLUMNS = ["#", "Tiêu đề", "Nguồn", "Loại", "Trạng thái", "Tiến độ", "Tốc độ"]


class QueueTab(QWidget):
    """Tab hàng đợi download."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window = window
        self._speed_track: dict[int, tuple[float, int]] = {}  # index -> (time, bytes)

        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.pause_btn = QPushButton("⏸ Tạm dừng tất cả")
        self.resume_btn = QPushButton("▶ Tiếp tục")
        self.cancel_btn = QPushButton("✖ Hủy tất cả")
        self.quota_label = QLabel("Quota API: —")
        controls.addWidget(self.pause_btn)
        controls.addWidget(self.resume_btn)
        controls.addWidget(self.cancel_btn)
        controls.addStretch()
        controls.addWidget(self.quota_label)
        root.addLayout(controls)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setItemDelegateForColumn(5, ProgressDelegate(self.table))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(1, 320)
        self.table.setColumnWidth(4, 90)
        self.table.setColumnWidth(5, 140)
        root.addWidget(self.table)

        self.pause_btn.clicked.connect(self._pause_all)
        self.resume_btn.clicked.connect(self._resume_all)
        self.cancel_btn.clicked.connect(self._cancel_all)

        self._quota_timer = QTimer(self)
        self._quota_timer.timeout.connect(self._refresh_quota)
        self._quota_timer.start(5000)

    # ---------- Đồng bộ hàng ----------

    def sync_rows(self) -> None:
        """Đảm bảo bảng có đủ hàng cho mọi job hiện có."""
        states = self.window.manager.states
        while self.table.rowCount() < len(states):
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col in range(len(_COLUMNS)):
                self.table.setItem(row, col, QTableWidgetItem(""))
            self._render_row(states[row])

    def _render_row(self, state: JobState) -> None:
        row = state.index - 1
        if row >= self.table.rowCount():
            self.sync_rows()
            return
        result = state.result
        self.table.item(row, 0).setText(str(state.index))
        self.table.item(row, 1).setText(result.title[:60])
        self.table.item(row, 2).setText(result.provider)
        self.table.item(row, 3).setText("ảnh" if result.media_type == "image" else "video")
        status_item = self.table.item(row, 4)
        status_item.setText(_STATUS_VN.get(state.status, str(state.status)))
        if state.error and state.status == JobStatus.FAILED:
            status_item.setToolTip(state.error)

        progress_item = self.table.item(row, 5)
        if state.bytes_total > 0:
            percent = min(100, state.bytes_done * 100 // state.bytes_total)
        elif state.status in (JobStatus.DONE, JobStatus.SKIPPED_DUPLICATE):
            percent = 100
        else:
            percent = 0
        progress_item.setData(PROGRESS_ROLE, percent)

        speed_item = self.table.item(row, 6)
        if state.status == JobStatus.DOWNLOADING:
            speed_item.setText(self._compute_speed(state))
        elif state.status in (JobStatus.DONE, JobStatus.SKIPPED_DUPLICATE, JobStatus.FAILED):
            speed_item.setText("")

    def _compute_speed(self, state: JobState) -> str:
        now = time.monotonic()
        last = self._speed_track.get(state.index)
        self._speed_track[state.index] = (now, state.bytes_done)
        if last is None:
            return "…"
        dt = now - last[0]
        if dt <= 0.05:
            return ""
        speed = (state.bytes_done - last[1]) / dt
        if speed <= 0:
            return ""
        if speed > 1024 * 1024:
            return f"{speed / 1024 / 1024:.1f} MB/s"
        return f"{speed / 1024:.0f} KB/s"

    # ---------- Slots ----------

    def on_job_updated(self, state: JobState) -> None:
        """Nhận signal từ QueueBridge (thread-safe) và cập nhật bảng."""
        self.sync_rows()
        self._render_row(state)
        if state.status == JobStatus.DONE:
            self.window.library_tab.schedule_refresh()

    def _refresh_quota(self) -> None:
        quota = self.window.manager.quota_remaining()
        text = " · ".join(f"{k}: {v}" for k, v in sorted(quota.items()))
        self.quota_label.setText(f"Quota API còn lại: {text}")

    def _pause_all(self) -> None:
        self.window.manager.pause_all()
        self.window.toast("Đã tạm dừng hàng đợi (job đang chạy sẽ dừng ở bước kế).")

    def _resume_all(self) -> None:
        self.window.manager.resume_all()
        self.window.toast("Tiếp tục hàng đợi.")

    def _cancel_all(self) -> None:
        self.window.manager.cancel_all()
        self.window.toast("Đã gửi lệnh hủy tất cả job chưa xong.")

    def _context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self.window.manager.states):
            return
        state = self.window.manager.states[row]
        menu = QMenu(self)
        cancel_action = menu.addAction(f"Hủy job #{state.index}")
        cancel_action.setEnabled(
            state.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING)
        )
        if menu.exec(self.table.viewport().mapToGlobal(pos)) == cancel_action:
            state.cancel_event.set()
            self.window.toast(f"Đã gửi lệnh hủy job #{state.index}.")
