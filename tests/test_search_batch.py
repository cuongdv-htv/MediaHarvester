"""Test tìm kiếm hàng loạt (batch) ở tab Tìm kiếm: gom nhiều project rồi tự thêm queue."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 chưa cài")

from mediaharvester.gui.search_tab import BatchEntry  # noqa: E402
from mediaharvester.providers.base import MediaType, Orientation, SearchResult  # noqa: E402


class _FakeProvider:
    """Provider giả: search() trả về danh sách kết quả dựng sẵn (có thể theo từng keyword)."""

    supported_types = {MediaType.IMAGE, MediaType.VIDEO}

    def __init__(self, per_keyword: int = 2, height: int = 1080) -> None:
        self.per_keyword = per_keyword
        self.height = height

    async def search(self, query, media_type, page=1, per_page=30):
        return [
            SearchResult(
                provider="fake",
                media_type=media_type,
                title=f"{query}-{i}",
                thumbnail_url="http://x/t.jpg",
                download_url=f"http://x/{query}-{i}.jpg",
                source_page_url="http://x/p",
                license="L",
                author=None,
                width=int(self.height * 16 / 9),
                height=self.height,
                duration_sec=None,
                extra={},
            )
            for i in range(self.per_keyword)
        ]


def _window(tmp_path, monkeypatch, provider=None):
    """Dựng MainWindow offscreen, nhồi fake provider + stub manager.add ghi lại lời gọi."""
    monkeypatch.chdir(tmp_path)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from mediaharvester.gui.main_window import MainWindow

    window = MainWindow()
    window.providers["fake"] = provider or _FakeProvider()
    calls: list[tuple[str, str, SearchResult]] = []
    window.manager.add = lambda result, keyword, project=None: calls.append(
        (project, keyword, result)
    )
    return app, window, calls


def _entry(project, keywords, min_height=0, per_page=30, media=(MediaType.IMAGE,)):
    return BatchEntry(
        project=project,
        keywords=tuple(keywords),
        providers=("fake",),
        media_types=tuple(media),
        per_page=per_page,
        min_height=min_height,
        orientation=Orientation.ANY,
    )


async def test_run_batch_them_het_ket_qua_dung_project(tmp_path, monkeypatch) -> None:
    """2 project × nhiều keyword → tự thêm hết kết quả, đúng project/keyword từng mục."""
    app, window, calls = _window(tmp_path, monkeypatch, _FakeProvider(per_keyword=2))
    tab = window.search_tab
    try:
        entries = [
            _entry("du-an-1", ["solar", "wind"]),  # 2 kw × 2 = 4
            _entry("du-an-2", ["city"]),           # 1 kw × 2 = 2
        ]
        added, n_projects = await tab._run_batch(entries)

        assert (added, n_projects) == (6, 2)
        assert len(calls) == 6
        assert {c[0] for c in calls} == {"du-an-1", "du-an-2"}
        # Kết quả của du-an-1 phải mang keyword solar/wind
        kw_da1 = {c[1] for c in calls if c[0] == "du-an-1"}
        assert kw_da1 == {"solar", "wind"}
    finally:
        window.close()
        app.processEvents()


async def test_run_batch_ap_dung_min_height_snapshot(tmp_path, monkeypatch) -> None:
    """Snapshot min_height cao hơn độ phân giải kết quả → lọc bỏ hết, không thêm gì."""
    app, window, calls = _window(tmp_path, monkeypatch, _FakeProvider(per_keyword=3, height=720))
    tab = window.search_tab
    try:
        added, _ = await tab._run_batch([_entry("p", ["kw"], min_height=2160)])
        assert added == 0
        assert calls == []
    finally:
        window.close()
        app.processEvents()


def test_add_to_batch_bo_qua_khi_khong_co_keyword(tmp_path, monkeypatch) -> None:
    """Bấm 'Thêm project hiện tại' khi ô từ khóa trống → không thêm dòng nào."""
    app, window, _ = _window(tmp_path, monkeypatch)
    tab = window.search_tab
    try:
        tab.query_edit.setPlainText("   \n  ")
        tab.on_add_to_batch()
        assert tab.batch_list.count() == 0
    finally:
        window.close()
        app.processEvents()


def test_add_to_batch_luu_snapshot_va_don_o_keyword(tmp_path, monkeypatch) -> None:
    """Thêm mục → lưu đúng snapshot (project + keywords) và xóa ô từ khóa để gõ mục kế."""
    app, window, _ = _window(tmp_path, monkeypatch)
    tab = window.search_tab
    try:
        tab.project_edit.setText("kinh-te")
        tab.query_edit.setPlainText("lam phat\nlai suat")
        # provider_checks dựng lúc tạo tab (trước khi inject 'fake') — chọn 1 nguồn có sẵn
        next(iter(tab.provider_checks.values())).setChecked(True)

        tab.on_add_to_batch()

        assert tab.batch_list.count() == 1
        entry = tab._batch_entries()[0]
        assert entry.project == "kinh-te"
        assert entry.keywords == ("lam phat", "lai suat")
        assert tab.query_edit.toPlainText() == ""  # đã dọn ô
        assert "🚀 Chạy tất cả (1)" == tab.batch_run_btn.text()
    finally:
        window.close()
        app.processEvents()
