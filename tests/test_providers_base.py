"""Test cho providers.base: registry và interface Provider."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from mediaharvester.providers.base import (
    MediaType,
    Orientation,
    Provider,
    SearchResult,
    classify_orientation,
    get_registry,
    passes_orientation,
    register_provider,
)


@register_provider
class DummyProvider(Provider):
    """Provider giả để test registry."""

    name = "dummy"
    supported_types = {MediaType.IMAGE}
    requires_api_key = False

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        return [
            SearchResult(
                provider=self.name,
                media_type=MediaType.IMAGE,
                title=query,
                thumbnail_url="http://example.com/t.jpg",
                download_url="http://example.com/f.jpg",
                source_page_url="http://example.com",
                license="CC0",
            )
        ]

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        progress_cb(1, 1)
        return dest_dir / "f.jpg"


def test_registry_contains_dummy() -> None:
    """Provider tự đăng ký qua decorator phải xuất hiện trong registry."""
    registry = get_registry()
    assert registry["dummy"] is DummyProvider


async def test_dummy_search_and_health_check() -> None:
    """Interface async hoạt động: search trả kết quả chuẩn, health_check mặc định True."""
    provider = DummyProvider()
    results = await provider.search("solar panel", MediaType.IMAGE)
    assert len(results) == 1
    assert results[0].provider == "dummy"
    assert results[0].media_type == MediaType.IMAGE
    assert results[0].extra == {}
    assert await provider.health_check() is True


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1920, 1080, Orientation.LANDSCAPE),
        (1080, 1920, Orientation.PORTRAIT),
        (1000, 1000, Orientation.SQUARE),
        (1080, 1000, Orientation.SQUARE),  # gần vuông → SQUARE
        (None, 1080, None),
        (1920, 0, None),
    ],
)
def test_classify_orientation(width, height, expected) -> None:
    """Phân loại hướng theo tỉ lệ rộng/cao; kích thước thiếu → None."""
    assert classify_orientation(width, height) == expected


def test_passes_orientation() -> None:
    """Lọc theo hướng; ANY và kích thước không rõ luôn qua."""
    assert passes_orientation(1920, 1080, Orientation.ANY)
    assert passes_orientation(1920, 1080, Orientation.LANDSCAPE)
    assert not passes_orientation(1920, 1080, Orientation.PORTRAIT)
    assert passes_orientation(1080, 1920, Orientation.PORTRAIT)
    assert passes_orientation(None, None, Orientation.PORTRAIT)  # không rõ → qua
