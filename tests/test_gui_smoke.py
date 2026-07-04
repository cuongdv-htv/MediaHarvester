"""Smoke test GUI: dựng MainWindow offscreen, đủ 4 tab, không crash."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 chưa cài")


def test_main_window_constructs(tmp_path, monkeypatch) -> None:
    """MainWindow dựng được với config mặc định trong thư mục tạm."""
    monkeypatch.chdir(tmp_path)  # library/, .env... nằm trong tmp
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from mediaharvester.gui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window.tabs.count() == 4
        titles = [window.tabs.tabText(i) for i in range(4)]
        assert any("Tìm kiếm" in t for t in titles)
        assert any("Hàng đợi" in t for t in titles)
        assert any("Thư viện" in t for t in titles)
        assert any("Cài đặt" in t for t in titles)
        # ytdlp không cần key nên luôn có mặt
        assert "ytdlp" in window.providers
    finally:
        window.close()
        app.processEvents()
