"""Anti-block helpers: fallback curl_cffi khi bị 403/blocked (ddgs, generic_scraper)."""

from __future__ import annotations

from pathlib import Path


def curl_fetch_file(url: str, dest: Path, ua: str) -> Path:
    """Tải file bằng curl_cffi impersonate Chrome (blocking — gọi qua to_thread)."""
    from curl_cffi import requests as curl_requests

    resp = curl_requests.get(url, impersonate="chrome", timeout=60, headers={"User-Agent": ua})
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def curl_fetch_text(url: str, ua: str) -> str:
    """Tải HTML bằng curl_cffi impersonate Chrome (blocking — gọi qua to_thread)."""
    from curl_cffi import requests as curl_requests

    resp = curl_requests.get(url, impersonate="chrome", timeout=60, headers={"User-Agent": ua})
    resp.raise_for_status()
    return resp.text
