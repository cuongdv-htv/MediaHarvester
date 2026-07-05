"""Providers: các nguồn media, tự đăng ký qua @register_provider."""

from __future__ import annotations


def load_all() -> None:
    """Import mọi module provider để trigger đăng ký vào registry.

    CLI và GUI đều gọi hàm này — thêm nguồn mới chỉ cần thêm 1 dòng import.
    """
    from mediaharvester.providers import (  # noqa: F401
        ddgs_images,
        gallerydl_provider,
        generic_scraper,
        nasa,
        openverse,
        pexels,
        pixabay,
        unsplash,
        wikimedia,
        ytdlp_provider,
    )
