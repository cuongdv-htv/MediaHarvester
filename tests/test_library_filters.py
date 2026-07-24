"""Test bộ lọc tab Thư viện: project mới phải xuất hiện trong dropdown sau khi tải."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 chưa cài")


def _combo_items(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def _make_result():
    from mediaharvester.providers.base import MediaType, SearchResult

    return SearchResult(
        provider="pexels",
        media_type=MediaType.IMAGE,
        title="anh test",
        thumbnail_url="http://x/t.jpg",
        download_url="http://x/a.jpg",
        source_page_url="http://x/p",
        license="Pexels License",
        author="ai do",
        width=1920,
        height=1080,
        duration_sec=None,
        extra={},
    )


def test_project_moi_hien_trong_dropdown_sau_khi_them_queue(tmp_path, monkeypatch) -> None:
    """Thêm job vào project mới → sau auto-refresh dropdown phải có project đó.

    Trước đây `reload_filters()` chỉ chạy lúc khởi động nên project mới không bao
    giờ xuất hiện cho tới khi khởi động lại app.
    """
    monkeypatch.chdir(tmp_path)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from mediaharvester.gui.main_window import MainWindow

    window = MainWindow()
    try:
        lib = window.library_tab
        assert "du-an-abc" not in _combo_items(lib.project_combo)

        window.manager.add(_make_result(), keyword="test", project="du-an-abc")
        # Đây là đường đi khi tải xong (queue_tab → schedule_refresh → timer)
        lib.reload_and_refresh()

        assert "du-an-abc" in _combo_items(lib.project_combo)
    finally:
        window.close()
        app.processEvents()


def test_nhan_nut_tai_doi_theo_lua_chon(tmp_path, monkeypatch) -> None:
    """'Tất cả project' → tải toàn bộ thư viện; chọn 1 project → tải riêng project đó."""
    monkeypatch.chdir(tmp_path)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from mediaharvester.gui.main_window import MainWindow

    window = MainWindow()
    try:
        lib = window.library_tab
        window.manager.add(_make_result(), keyword="test", project="du-an-abc")
        lib.reload_and_refresh()

        lib.project_combo.setCurrentIndex(0)  # Tất cả project
        assert "toàn bộ thư viện" in lib.download_project_btn.text()

        lib.project_combo.setCurrentIndex(lib.project_combo.findText("du-an-abc"))
        assert "du-an-abc" in lib.download_project_btn.text()
    finally:
        window.close()
        app.processEvents()


def test_reload_filters_giu_nguyen_lua_chon(tmp_path, monkeypatch) -> None:
    """Nạp lại bộ lọc không được làm mất project người dùng đang chọn."""
    monkeypatch.chdir(tmp_path)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from mediaharvester.gui.main_window import MainWindow

    window = MainWindow()
    try:
        lib = window.library_tab
        window.manager.add(_make_result(), keyword="test", project="du-an-abc")
        lib.reload_and_refresh()
        lib.project_combo.setCurrentText("du-an-abc")

        # Thêm project thứ hai rồi nạp lại — lựa chọn cũ phải còn nguyên
        window.manager.add(_make_result(), keyword="test", project="du-an-xyz")
        lib.reload_and_refresh()

        assert lib.project_combo.currentText() == "du-an-abc"
        assert "du-an-xyz" in _combo_items(lib.project_combo)
    finally:
        window.close()
        app.processEvents()
