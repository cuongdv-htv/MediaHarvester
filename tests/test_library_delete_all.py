"""Test xóa toàn bộ project (có chừa project được giữ) ở tab Thư viện."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 chưa cài")

from sqlmodel import select  # noqa: E402

from mediaharvester.core.database import get_or_create_project, get_session  # noqa: E402
from mediaharvester.core.models import Asset, Project  # noqa: E402


def _seed(window, project: str, n: int) -> None:
    """Tạo project + n asset (record DB) cho project đó."""
    with get_session(window.engine) as session:
        pid = get_or_create_project(session, project).id
        for i in range(n):
            session.add(
                Asset(
                    project_id=pid,
                    file_path=f"library/{project}/image/kw/f{i}.jpg",
                    media_type="image",
                    provider="pexels",
                    source_url="u",
                    source_page_url="u",
                    license="L",
                    title=f"t{i}",
                )
            )
        session.commit()


def _project_names(window) -> list[str]:
    with get_session(window.engine) as session:
        return sorted(session.exec(select(Project.name)).all())


def _asset_total(window) -> int:
    with get_session(window.engine) as session:
        return len(session.exec(select(Asset)).all())


def test_remove_projects_from_db_chua_project_duoc_giu(tmp_path, monkeypatch) -> None:
    """Xóa 2 project, chừa lại project không nằm trong danh sách xóa."""
    monkeypatch.chdir(tmp_path)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from mediaharvester.gui.main_window import MainWindow

    window = MainWindow()
    try:
        _seed(window, "du-an-1", 2)
        _seed(window, "du-an-2", 3)
        _seed(window, "test-project", 1)  # project test được giữ

        removed = window.library_tab._remove_projects_from_db(["du-an-1", "du-an-2"])

        assert removed == 5  # 2 + 3 asset đã gỡ
        assert "test-project" in _project_names(window)
        assert "du-an-1" not in _project_names(window)
        assert "du-an-2" not in _project_names(window)
        assert _asset_total(window) == 1  # chỉ còn asset của test-project
    finally:
        window.close()
        app.processEvents()


def test_remove_projects_bo_qua_ten_khong_ton_tai(tmp_path, monkeypatch) -> None:
    """Tên project không tồn tại thì bỏ qua, không làm hỏng cả lượt xóa."""
    monkeypatch.chdir(tmp_path)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from mediaharvester.gui.main_window import MainWindow

    window = MainWindow()
    try:
        _seed(window, "du-an-1", 2)

        removed = window.library_tab._remove_projects_from_db(["du-an-1", "khong-co"])

        assert removed == 2
        assert "du-an-1" not in _project_names(window)
    finally:
        window.close()
        app.processEvents()
