"""Test cho providers.base: registry và interface Provider."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mediaharvester.providers.base import (
    MediaType,
    Provider,
    SearchResult,
    get_registry,
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
