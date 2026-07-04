"""Test DownloadManager end-to-end với provider giả (không cần mạng).

Regression: chạy lại cùng URL → tên file deterministic ghi đè file gốc,
dedup không được xóa nhầm bản gốc.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlmodel import select

from mediaharvester.core.config import AppConfig
from mediaharvester.core.database import get_engine, get_session, init_db
from mediaharvester.core.downloader import DownloadManager, JobStatus
from mediaharvester.core.models import Asset
from mediaharvester.providers.base import MediaType, Provider, SearchResult


class FixedFileProvider(Provider):
    """Provider giả: 'tải' bằng cách ghi nội dung cố định vào cùng một tên file."""

    name = "fixedtest"
    supported_types = {MediaType.IMAGE}
    requires_api_key = False

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        return []

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "fixedtest_media_abc12345.jpg"
        dest.write_bytes(b"noi dung co dinh de sha256 luon giong nhau")
        progress_cb(1, 1)
        return dest


def _result() -> SearchResult:
    return SearchResult(
        provider="fixedtest",
        media_type=MediaType.IMAGE,
        title="media",
        thumbnail_url="",
        download_url="https://example.com/media.jpg",
        source_page_url="https://example.com",
        license="CC0",
    )


async def test_rerun_same_url_keeps_original_file(tmp_path: Path) -> None:
    """Chạy 2 lần cùng URL: lần 2 skip duplicate nhưng file gốc PHẢI còn nguyên."""
    config = AppConfig(library_root=tmp_path / "lib")
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    provider = FixedFileProvider()

    # Lần 1: tải bình thường → done
    mgr1 = DownloadManager(config, engine, {"fixedtest": provider}, "proj")
    mgr1.add(_result(), keyword="tua bin gió")
    await mgr1.run()
    assert mgr1.states[0].status == JobStatus.DONE
    file_path = mgr1.states[0].file_path
    assert file_path is not None and file_path.exists()

    # Lần 2: cùng URL → skip duplicate, file gốc vẫn tồn tại
    mgr2 = DownloadManager(config, engine, {"fixedtest": provider}, "proj")
    mgr2.add(_result(), keyword="tua bin gió")
    await mgr2.run()
    assert mgr2.states[0].status == JobStatus.SKIPPED_DUPLICATE
    assert file_path.exists(), "Bug: dedup xóa nhầm file gốc khi chạy lại cùng URL"

    # DB chỉ có đúng 1 asset
    with get_session(engine) as session:
        assets = session.exec(select(Asset)).all()
    assert len(assets) == 1
    assert Path(assets[0].file_path) == file_path
