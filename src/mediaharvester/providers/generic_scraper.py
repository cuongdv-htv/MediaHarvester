"""Generic scraper: nhập URL trang bất kỳ → liệt kê ảnh/video tìm được.

- Parse HTML tĩnh bằng selectolax (img/src/srcset, video/source, og:image).
- Anti-block: UA pool, honor robots.txt (config override được), 403 → curl_cffi.
- Trang render bằng JS: fallback playwright (optional extra, lazy import) —
  chỉ khi đã cài `uv sync --extra scraper && uv run playwright install chromium`.
"""

from __future__ import annotations

import asyncio
import urllib.robotparser
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger
from selectolax.parser import HTMLParser

from mediaharvester.core.downloader import download_with_retry
from mediaharvester.core.organizer import build_filename, ext_from_url
from mediaharvester.providers.base import (
    MediaType,
    Provider,
    SearchResult,
    register_provider,
)
from mediaharvester.utils.anti_block import curl_fetch_file, curl_fetch_text
from mediaharvester.utils.ua_pool import polite_delay, random_ua

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}


def _url_ext(url: str) -> str:
    return PurePosixPath(urlparse(url).path).suffix.lower()


def extract_media_urls(html: str, base_url: str) -> list[tuple[str, MediaType, str]]:
    """Parse HTML → danh sách (url, media_type, title) đã dedupe, giữ thứ tự."""
    tree = HTMLParser(html)
    seen: set[str] = set()
    found: list[tuple[str, MediaType, str]] = []

    def add(raw_url: str | None, media_type: MediaType, title: str = "") -> None:
        if not raw_url:
            return
        url = urljoin(base_url, raw_url.strip())
        if not url.startswith(("http://", "https://")) or url in seen:
            return
        ext = _url_ext(url)
        if media_type == MediaType.IMAGE and ext and ext not in _IMAGE_EXTS:
            return
        if media_type == MediaType.VIDEO and ext and ext not in _VIDEO_EXTS:
            return
        seen.add(url)
        found.append((url, media_type, title or PurePosixPath(urlparse(url).path).stem))

    # og:image / og:video
    for meta in tree.css('meta[property="og:image"], meta[property="og:image:url"]'):
        add(meta.attributes.get("content"), MediaType.IMAGE, "og-image")
    for meta in tree.css('meta[property="og:video"], meta[property="og:video:url"]'):
        add(meta.attributes.get("content"), MediaType.VIDEO, "og-video")

    # <img>: src, data-src, srcset (lấy ứng viên cuối — thường lớn nhất)
    for img in tree.css("img"):
        attrs = img.attributes
        title = (attrs.get("alt") or "").strip()
        srcset = attrs.get("srcset") or attrs.get("data-srcset")
        if srcset:
            last = srcset.split(",")[-1].strip().split(" ")[0]
            add(last, MediaType.IMAGE, title)
        add(attrs.get("src") or attrs.get("data-src"), MediaType.IMAGE, title)

    # <video> + <source>
    for video in tree.css("video"):
        add(video.attributes.get("src"), MediaType.VIDEO)
    for source in tree.css("video source, source"):
        src_type = source.attributes.get("type") or ""
        media_type = MediaType.VIDEO if "video" in src_type or not src_type else MediaType.IMAGE
        add(source.attributes.get("src"), media_type)

    # <a href="...jpg/mp4"> link trực tiếp tới file media
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        ext = _url_ext(href)
        if ext in _IMAGE_EXTS:
            add(href, MediaType.IMAGE, (a.text() or "").strip())
        elif ext in _VIDEO_EXTS:
            add(href, MediaType.VIDEO, (a.text() or "").strip())

    return found


@register_provider
class GenericScraperProvider(Provider):
    """Quét media từ URL trang web bất kỳ. Không hỗ trợ search từ khóa."""

    name = "scraper"
    supported_types = {MediaType.IMAGE, MediaType.VIDEO}
    requires_api_key = False

    def __init__(
        self,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
        honor_robots: bool = True,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=30)
        self.honor_robots = honor_robots

    async def search(
        self, query: str, media_type: MediaType, page: int = 1, per_page: int = 30
    ) -> list[SearchResult]:
        """Scraper không search từ khóa — dùng scrape(url)."""
        return []

    async def _robots_allows(self, page_url: str, ua: str) -> bool:
        """Kiểm tra robots.txt (bỏ qua nếu không đọc được — không chặn oan)."""
        parsed = urlparse(page_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            resp = await self._client.get(
                robots_url, headers={"User-Agent": ua}, follow_redirects=True
            )
            if resp.status_code != 200:
                return True
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(resp.text.splitlines())
            return parser.can_fetch("*", page_url)
        except httpx.HTTPError:
            return True

    async def scrape(self, page_url: str) -> list[SearchResult]:
        """Tải trang, parse media; ít kết quả → thử playwright (nếu đã cài)."""
        ua = random_ua()
        if self.honor_robots and not await self._robots_allows(page_url, ua):
            raise ValueError(
                f"robots.txt của trang không cho phép quét: {page_url}\n"
                "(có thể tắt kiểm tra trong config.toml: [anti_block] honor_robots_txt = false)"
            )

        await polite_delay(1.0, 3.0)
        html = await self._fetch_html(page_url, ua)
        media = extract_media_urls(html, page_url)

        if len(media) < 3:
            rendered = await self._try_playwright(page_url)
            if rendered:
                media = extract_media_urls(rendered, page_url) or media

        results = [
            SearchResult(
                provider=self.name,
                media_type=media_type,
                title=title or "media",
                thumbnail_url=url if media_type == MediaType.IMAGE else "",
                download_url=url,
                source_page_url=page_url,
                license="unknown (web scrape — tự kiểm tra bản quyền)",
                author=urlparse(page_url).netloc,
            )
            for url, media_type, title in media
        ]
        logger.info("Scraper: tìm thấy {} media tại {}", len(results), page_url)
        return results

    async def _fetch_html(self, url: str, ua: str) -> str:
        """GET HTML với UA thật; 403 → fallback curl_cffi."""
        try:
            resp = await self._client.get(
                url, headers={"User-Agent": ua}, follow_redirects=True
            )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (403, 429):
                raise
            logger.info("Scraper bị {} — fallback curl_cffi.", exc.response.status_code)
            return await asyncio.to_thread(curl_fetch_text, url, ua)

    async def _try_playwright(self, url: str) -> str | None:
        """Render trang bằng playwright nếu đã cài (optional extra) — không thì bỏ qua."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.info(
                "Trang có vẻ render bằng JS nhưng playwright chưa cài — "
                "cài bằng: uv sync --extra scraper && uv run playwright install chromium"
            )
            return None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=random_ua())
                await page.goto(url, wait_until="networkidle", timeout=30000)
                html = await page.content()
                await browser.close()
                return html
        except Exception as exc:
            logger.warning("Playwright render lỗi: {}", exc)
            return None

    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải file media đã quét (delay lịch sự + UA; 403 → curl_cffi)."""
        url = result.download_url
        ua = random_ua()
        default_ext = ".jpg" if result.media_type == MediaType.IMAGE else ".mp4"
        dest = dest_dir / build_filename(
            self.name, result.title, ext_from_url(url, default_ext), url
        )
        await polite_delay(1.0, 3.0)
        try:
            return await download_with_retry(
                self._client, url, dest, progress_cb, headers={"User-Agent": ua}
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (403, 429):
                raise
            logger.info("Scraper bị {} khi tải — fallback curl_cffi.", exc.response.status_code)
            path = await asyncio.to_thread(curl_fetch_file, url, dest, ua)
            progress_cb(path.stat().st_size, path.stat().st_size)
            return path

    async def health_check(self) -> bool:
        """Scraper không phụ thuộc dịch vụ ngoài — luôn sẵn sàng."""
        return True
