"""Test generic_scraper: parse HTML → media URLs + scrape qua respx."""

from __future__ import annotations

import httpx
import respx

from mediaharvester.providers.base import MediaType
from mediaharvester.providers.generic_scraper import (
    GenericScraperProvider,
    extract_media_urls,
)

HTML = """
<html><head>
  <meta property="og:image" content="/og/cover.jpg">
</head><body>
  <img src="/images/photo1.jpg" alt="Nhà máy điện gió">
  <img data-src="https://cdn.example.com/lazy.webp" alt="lazy">
  <img srcset="/i/small.jpg 480w, /i/large.jpg 1920w" src="/i/mid.jpg" alt="responsive">
  <img src="/assets/icon.svg" alt="svg bị loại">
  <img src="data:image/png;base64,xxx" alt="data uri bị loại">
  <video src="/media/clip.mp4"></video>
  <video><source src="/media/clip2.webm" type="video/webm"></video>
  <a href="/files/anh-chup.png">Ảnh gốc</a>
  <a href="/files/video-goc.mp4">Video gốc</a>
  <a href="/page.html">Trang khác (bỏ qua)</a>
  <img src="/images/photo1.jpg" alt="trùng — chỉ tính 1 lần">
</body></html>
"""


def test_extract_media_urls() -> None:
    media = extract_media_urls(HTML, "https://example.com/gallery")
    urls = {url for url, _, _ in media}

    assert "https://example.com/og/cover.jpg" in urls
    assert "https://example.com/images/photo1.jpg" in urls
    assert "https://cdn.example.com/lazy.webp" in urls
    assert "https://example.com/i/large.jpg" in urls  # srcset lấy ứng viên lớn nhất
    assert "https://example.com/media/clip.mp4" in urls
    assert "https://example.com/media/clip2.webm" in urls
    assert "https://example.com/files/anh-chup.png" in urls
    assert "https://example.com/files/video-goc.mp4" in urls
    # Loại: svg, data URI, link trang html
    assert not any("icon.svg" in u for u in urls)
    assert not any(u.startswith("data:") for u in urls)
    assert not any("page.html" in u for u in urls)
    # Dedupe: photo1.jpg chỉ 1 lần
    assert sum(1 for u in urls if "photo1.jpg" in u) == 1


def test_extract_media_types() -> None:
    media = extract_media_urls(HTML, "https://example.com/")
    types = {url: mt for url, mt, _ in media}
    assert types["https://example.com/media/clip.mp4"] == MediaType.VIDEO
    assert types["https://example.com/images/photo1.jpg"] == MediaType.IMAGE


def test_extract_title_from_alt() -> None:
    media = extract_media_urls(HTML, "https://example.com/")
    titles = {url: title for url, _, title in media}
    assert titles["https://example.com/images/photo1.jpg"] == "Nhà máy điện gió"


@respx.mock
async def test_scrape_end_to_end() -> None:
    respx.get("https://example.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/gallery").mock(
        return_value=httpx.Response(200, text=HTML)
    )
    async with httpx.AsyncClient() as client:
        provider = GenericScraperProvider(client=client, honor_robots=True)
        results = await provider.scrape("https://example.com/gallery")
    assert len(results) >= 7
    r = results[0]
    assert r.provider == "scraper"
    assert r.source_page_url == "https://example.com/gallery"
    assert "unknown" in r.license


@respx.mock
async def test_scrape_respects_robots() -> None:
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /")
    )
    async with httpx.AsyncClient() as client:
        provider = GenericScraperProvider(client=client, honor_robots=True)
        try:
            await provider.scrape("https://example.com/gallery")
            raise AssertionError("Phải raise ValueError vì robots.txt cấm")
        except ValueError as exc:
            assert "robots.txt" in str(exc)


@respx.mock
async def test_scrape_robots_override() -> None:
    """honor_robots=False → quét được dù robots cấm."""
    respx.get("https://example.com/gallery").mock(
        return_value=httpx.Response(200, text=HTML)
    )
    async with httpx.AsyncClient() as client:
        provider = GenericScraperProvider(client=client, honor_robots=False)
        results = await provider.scrape("https://example.com/gallery")
    assert results
