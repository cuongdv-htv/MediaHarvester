"""ProgressDelegate: vẽ progress bar trong ô bảng Queue (nhẹ hơn cell widget)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
)

PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 1


class ProgressDelegate(QStyledItemDelegate):
    """Đọc % từ PROGRESS_ROLE của index và vẽ thanh tiến độ."""

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        percent = index.data(PROGRESS_ROLE)
        if percent is None:
            super().paint(painter, option, index)
            return
        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(4, 6, -4, -6)
        bar.minimum = 0
        bar.maximum = 100
        bar.progress = int(percent)
        bar.text = f"{int(percent)}%"
        bar.textVisible = True
        QApplication.style().drawControl(QStyle.ControlElement.CE_ProgressBar, bar, painter)
