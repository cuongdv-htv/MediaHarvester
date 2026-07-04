"""Provider interface chuẩn + registry tự động.

Mọi nguồn media đều implement `Provider` và tự đăng ký qua decorator
`@register_provider` — GUI/CLI đọc registry để biết các nguồn khả dụng.
Thêm nguồn mới = thêm 1 file, không sửa core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class MediaType(StrEnum):
    """Loại media hỗ trợ."""

    IMAGE = "image"
    VIDEO = "video"


@dataclass
class SearchResult:
    """Một kết quả tìm kiếm chuẩn hóa từ bất kỳ provider nào."""

    provider: str
    media_type: MediaType
    title: str
    thumbnail_url: str
    download_url: str  # hoặc page_url nếu cần resolve (yt-dlp)
    source_page_url: str
    license: str  # "Pexels License", "CC0", "unknown"...
    author: str | None = None
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None  # video
    extra: dict = field(default_factory=dict)  # provider-specific


class Provider(ABC):
    """Interface chuẩn mọi nguồn media phải implement."""

    name: str
    supported_types: set[MediaType]
    requires_api_key: bool = False

    @abstractmethod
    async def search(
        self,
        query: str,
        media_type: MediaType,
        page: int = 1,
        per_page: int = 30,
    ) -> list[SearchResult]:
        """Tìm kiếm media theo từ khóa, trả về danh sách kết quả chuẩn hóa."""

    @abstractmethod
    async def download(
        self,
        result: SearchResult,
        dest_dir: Path,
        progress_cb: Callable[[int, int], None],
        quality: str = "1080p",
    ) -> Path:
        """Tải media về `dest_dir`, báo tiến độ qua `progress_cb(done, total)`."""

    async def health_check(self) -> bool:
        """Kiểm tra API key / kết nối. Mặc định coi như OK."""
        return True


_REGISTRY: dict[str, type[Provider]] = {}


def register_provider(cls: type[Provider]) -> type[Provider]:
    """Decorator: đăng ký provider vào registry toàn cục theo `cls.name`."""
    _REGISTRY[cls.name] = cls
    return cls


def get_registry() -> dict[str, type[Provider]]:
    """Trả về bản sao registry {name: provider_class}."""
    return dict(_REGISTRY)
