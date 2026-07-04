"""ResultGrid: lưới thumbnail dùng chung cho Search tab (checkable) và Library tab."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from mediaharvester.gui.widgets.thumbs import load_pixmap_cached

ITEM_DATA_ROLE = Qt.ItemDataRole.UserRole


class ResultGrid(QListWidget):
    """QListWidget chế độ IconMode hiển thị lưới thumbnail."""

    def __init__(self, checkable: bool = True, icon_size: int = 160) -> None:
        super().__init__()
        self._checkable = checkable
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(icon_size, int(icon_size * 0.75)))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(8)
        self.setWordWrap(True)
        self.setGridSize(QSize(icon_size + 16, int(icon_size * 0.75) + 52))
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def add_card(self, label: str, payload: object) -> QListWidgetItem:
        """Thêm 1 ô kết quả; payload gắn vào UserRole để lấy lại khi xử lý."""
        item = QListWidgetItem(label)
        item.setData(ITEM_DATA_ROLE, payload)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        if self._checkable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        self.addItem(item)
        return item

    def set_thumb(self, row: int, path: str) -> None:
        """Gắn thumbnail (load qua QPixmapCache) cho item ở hàng `row`."""
        if 0 <= row < self.count():
            pixmap = load_pixmap_cached(path)
            if not pixmap.isNull():
                self.item(row).setIcon(QIcon(pixmap))

    def checked_payloads(self) -> list[object]:
        """Danh sách payload của các item được tick."""
        return [
            self.item(i).data(ITEM_DATA_ROLE)
            for i in range(self.count())
            if self.item(i).checkState() == Qt.CheckState.Checked
        ]

    def set_all_checked(self, checked: bool) -> None:
        """Tick / bỏ tick tất cả."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.count()):
            self.item(i).setCheckState(state)
