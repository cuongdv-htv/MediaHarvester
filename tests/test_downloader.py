"""Test cho core.downloader: retry (tenacity), 429 Retry-After, resume Range."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from mediaharvester.core.downloader import RateLimiter, download_with_retry

URL = "https://cdn.example.com/media/file.bin"


@respx.mock
async def test_retry_500_then_success(tmp_path: Path) -> None:
    """Lần 1 lỗi 500 → retry → lần 2 thành công."""
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, content=b"hello world")]
    )
    async with httpx.AsyncClient() as client:
        dest = await download_with_retry(
            client, URL, tmp_path / "f.bin", wait_multiplier=0.01
        )
    assert dest.read_bytes() == b"hello world"
    assert route.call_count == 2
    assert not (tmp_path / "f.bin.part").exists()


@respx.mock
async def test_retry_429_honors_retry_after(tmp_path: Path) -> None:
    """429 → đọc Retry-After rồi thử lại."""
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, content=b"ok"),
        ]
    )
    async with httpx.AsyncClient() as client:
        dest = await download_with_retry(client, URL, tmp_path / "f.bin")
    assert dest.read_bytes() == b"ok"
    assert route.call_count == 2


@respx.mock
async def test_no_retry_on_404(tmp_path: Path) -> None:
    """404 không phải lỗi tạm thời → fail ngay, không retry."""
    route = respx.get(URL).mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await download_with_retry(client, URL, tmp_path / "f.bin")
    assert route.call_count == 1


@respx.mock
async def test_gives_up_after_max_attempts(tmp_path: Path) -> None:
    """Lỗi 500 liên tục → bỏ cuộc sau max_attempts lần."""
    route = respx.get(URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await download_with_retry(
                client, URL, tmp_path / "f.bin", max_attempts=3, wait_multiplier=0.01
            )
    assert route.call_count == 3


@respx.mock
async def test_resume_with_range_header(tmp_path: Path) -> None:
    """Có sẵn .part → gửi Range, server trả 206 → nối tiếp đúng nội dung."""
    dest = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(b"hel")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Range") == "bytes=3-"
        return httpx.Response(
            206, content=b"lo", headers={"Content-Range": "bytes 3-4/5"}
        )

    respx.get(URL).mock(side_effect=handler)
    async with httpx.AsyncClient() as client:
        await download_with_retry(client, URL, dest)
    assert dest.read_bytes() == b"hello"


@respx.mock
async def test_restart_when_server_ignores_range(tmp_path: Path) -> None:
    """Server không hỗ trợ Range (trả 200) → tải lại từ đầu, không nối bậy."""
    dest = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(b"xxx")
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"hello"))
    async with httpx.AsyncClient() as client:
        await download_with_retry(client, URL, dest)
    assert dest.read_bytes() == b"hello"


async def test_rate_limiter_consumes_tokens() -> None:
    """RateLimiter trừ token mỗi lần acquire, remaining giảm dần."""
    limiter = RateLimiter(per_hour=100)
    start = limiter.remaining
    await limiter.acquire()
    await limiter.acquire()
    assert limiter.remaining <= start - 1
