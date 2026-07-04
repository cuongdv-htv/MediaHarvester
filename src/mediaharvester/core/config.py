"""Cấu hình ứng dụng.

- API keys: đọc từ file `.env` qua pydantic-settings (không bao giờ lưu trong code/DB).
- Cấu hình chung: đọc từ `config.toml` (tomllib), thiếu file thì dùng mặc định.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiKeys(BaseSettings):
    """API keys của các provider, đọc từ file .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    unsplash_access_key: str = ""


class DownloadConfig(BaseModel):
    """Cấu hình tải xuống song song."""

    max_concurrent: int = 4
    max_per_domain: int = 2


class DedupConfig(BaseModel):
    """Cấu hình khử trùng lặp (sha256 + pHash)."""

    phash_threshold: int = 5
    auto_skip_duplicates: bool = False


class AntiBlockConfig(BaseModel):
    """Cấu hình chống chặn (chỉ áp dụng cho ddgs / generic_scraper)."""

    honor_robots_txt: bool = True


class YtDlpConfig(BaseModel):
    """Cấu hình yt-dlp: cookies từ browser cho các trang cần đăng nhập (X/Instagram)."""

    cookies_from_browser: str | None = None  # "chrome" | "edge" | "firefox" | None


def _default_rate_limits() -> dict[str, int]:
    return {"pexels": 200, "pixabay": 100, "unsplash": 50}


class AppConfig(BaseModel):
    """Cấu hình chung của app, đọc từ config.toml."""

    library_root: Path = Path("library")
    default_quality: str = "1080p"
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    anti_block: AntiBlockConfig = Field(default_factory=AntiBlockConfig)
    ytdlp: YtDlpConfig = Field(default_factory=YtDlpConfig)
    rate_limits: dict[str, int] = Field(default_factory=_default_rate_limits)


def load_config(path: Path | None = None) -> AppConfig:
    """Đọc config.toml tại `path` (mặc định ./config.toml).

    Không có file → trả về cấu hình mặc định. File hỏng sẽ raise để caller
    hiển thị lỗi thân thiện (không nuốt exception im lặng).
    """
    path = path or Path("config.toml")
    if not path.exists():
        return AppConfig()

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    general = data.get("general", {})
    return AppConfig(
        library_root=Path(general.get("library_root", "library")),
        default_quality=general.get("default_quality", "1080p"),
        download=DownloadConfig(**data.get("download", {})),
        dedup=DedupConfig(**data.get("dedup", {})),
        anti_block=AntiBlockConfig(**data.get("anti_block", {})),
        ytdlp=YtDlpConfig(**data.get("ytdlp", {})),
        rate_limits=data.get("rate_limits") or _default_rate_limits(),
    )
