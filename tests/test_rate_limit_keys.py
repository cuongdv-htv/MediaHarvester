"""Test quota rate-limit phải nhân theo số API key đang xoay vòng."""

from __future__ import annotations

from pathlib import Path

import httpx

from mediaharvester.core.config import AppConfig
from mediaharvester.core.database import get_engine, init_db
from mediaharvester.core.downloader import DownloadManager
from mediaharvester.providers.pexels import PexelsProvider


def _manager(tmp_path: Path, providers: dict) -> DownloadManager:
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    return DownloadManager(AppConfig(), engine, providers, project_name="p")


def test_quota_nhan_theo_so_key(tmp_path) -> None:
    """30 key → quota gấp 30 lần hạn mức của 1 key (không tự chờ ở mức 1 key)."""
    provider = PexelsProvider(api_keys=[f"k{i}" for i in range(30)], client=httpx.AsyncClient())
    manager = _manager(tmp_path, {"pexels": provider})

    assert manager.quota_remaining()["pexels"] == 200 * 30


def test_mot_key_giu_nguyen_han_muc(tmp_path) -> None:
    """1 key → quota đúng bằng cấu hình, không đổi hành vi cũ."""
    provider = PexelsProvider(api_keys=["k1"], client=httpx.AsyncClient())
    manager = _manager(tmp_path, {"pexels": provider})

    assert manager.quota_remaining()["pexels"] == 200


def test_provider_khong_co_pool_van_chay(tmp_path) -> None:
    """Provider không dùng key (ddgs/ytdlp...) vẫn giữ hạn mức cấu hình."""
    manager = _manager(tmp_path, {})

    assert manager.quota_remaining()["pexels"] == 200
