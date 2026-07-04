"""Integration tests Phase 4: gọi API thật (marker `integration`).

- Chạy riêng: `uv run pytest -m integration`
- Bỏ qua khi chạy unit: `uv run pytest -m "not integration"`
- Provider cần key sẽ tự skip nếu .env thiếu key.
"""

from __future__ import annotations

import httpx
import pytest

from mediaharvester.core.config import ApiKeys
from mediaharvester.providers.base import MediaType

pytestmark = pytest.mark.integration

_KEYS = ApiKeys()


@pytest.fixture
async def client():
    async with httpx.AsyncClient(timeout=30) as c:
        yield c


def _assert_valid(results: list, provider: str) -> None:
    assert results, f"{provider}: không có kết quả"
    r = results[0]
    assert r.provider == provider
    assert r.download_url
    assert r.license
    assert r.title


@pytest.mark.skipif(not _KEYS.pexels_api_key, reason="thiếu PEXELS_API_KEY")
async def test_pexels_search_real(client) -> None:
    from mediaharvester.providers.pexels import PexelsProvider

    results = await PexelsProvider(_KEYS.pexels_api_key, client).search(
        "mountain", MediaType.IMAGE, per_page=3
    )
    _assert_valid(results, "pexels")


@pytest.mark.skipif(not _KEYS.pixabay_api_key, reason="thiếu PIXABAY_API_KEY")
async def test_pixabay_search_real(client) -> None:
    from mediaharvester.providers.pixabay import PixabayProvider

    results = await PixabayProvider(_KEYS.pixabay_api_key, client).search(
        "mountain", MediaType.IMAGE, per_page=3
    )
    _assert_valid(results, "pixabay")


@pytest.mark.skipif(not _KEYS.unsplash_access_key, reason="thiếu UNSPLASH_ACCESS_KEY")
async def test_unsplash_search_real(client) -> None:
    from mediaharvester.providers.unsplash import UnsplashProvider

    results = await UnsplashProvider(_KEYS.unsplash_access_key, client).search(
        "mountain", MediaType.IMAGE, per_page=3
    )
    _assert_valid(results, "unsplash")


async def test_openverse_search_real(client) -> None:
    from mediaharvester.providers.openverse import OpenverseProvider

    results = await OpenverseProvider(client=client).search(
        "mountain", MediaType.IMAGE, per_page=3
    )
    _assert_valid(results, "openverse")
    assert results[0].license.startswith(("CC", "PDM", "unknown"))


async def test_wikimedia_search_real(client) -> None:
    from mediaharvester.providers.wikimedia import WikimediaProvider

    results = await WikimediaProvider(client=client).search(
        "wind turbine", MediaType.IMAGE, per_page=3
    )
    _assert_valid(results, "wikimedia")


async def test_nasa_search_real(client) -> None:
    from mediaharvester.providers.nasa import NasaProvider

    results = await NasaProvider(client=client).search("mars", MediaType.IMAGE, per_page=3)
    _assert_valid(results, "nasa")


async def test_ddgs_search_real(client) -> None:
    from mediaharvester.providers.ddgs_images import DdgsImagesProvider

    results = await DdgsImagesProvider(client=client).search(
        "wind turbine", MediaType.IMAGE, per_page=3
    )
    _assert_valid(results, "ddgs")


async def test_gallerydl_health_real() -> None:
    from mediaharvester.providers.gallerydl_provider import GalleryDlProvider

    assert await GalleryDlProvider().health_check() is True
