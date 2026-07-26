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
    """API keys của các provider, đọc từ file .env.

    Mỗi trường có thể chứa **nhiều key** cách nhau bởi dấu phẩy / xuống dòng để
    dùng cùng cơ chế xoay vòng (khi 1 key chạm giới hạn free thì đổi key kế tiếp).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    unsplash_access_key: str = ""

    def keys_for(self, provider: str) -> list[str]:
        """Danh sách key của 1 provider (đã tách, bỏ trùng, giữ thứ tự)."""
        from mediaharvester.core.keypool import split_keys

        raw = {
            "pexels": self.pexels_api_key,
            "pixabay": self.pixabay_api_key,
            "unsplash": self.unsplash_access_key,
        }.get(provider, "")
        seen: set[str] = set()
        out: list[str] = []
        for k in split_keys(raw):
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out


class DownloadConfig(BaseModel):
    """Cấu hình tải xuống song song."""

    max_concurrent: int = 4
    max_per_domain: int = 2


class DedupConfig(BaseModel):
    """Cấu hình khử trùng lặp (sha256 + pHash).

    `allow_duplicates=True` (mặc định): CHO PHÉP tải trùng — không bỏ qua ảnh/video
    trùng nội dung (chỉ bỏ qua khi tải lại đúng cùng một file vật lý). Tắt đi để
    quay lại chế độ khử trùng lặp (bỏ qua sha256 trùng + pHash gần trùng).
    """

    phash_threshold: int = 5
    auto_skip_duplicates: bool = False
    allow_duplicates: bool = True


class AntiBlockConfig(BaseModel):
    """Cấu hình chống chặn (chỉ áp dụng cho ddgs / generic_scraper)."""

    honor_robots_txt: bool = True


class YtDlpConfig(BaseModel):
    """Cấu hình yt-dlp: cookies từ browser cho các trang cần đăng nhập (X/Instagram)."""

    cookies_from_browser: str | None = None  # "chrome" | "edge" | "firefox" | None


class KeyRotationConfig(BaseModel):
    """Cấu hình xoay vòng API key khi chạm giới hạn free.

    - `cooldown_sec = 0` → key chạm giới hạn nghỉ tới hết ngày; >0 → nghỉ đúng số giây.
      (Header `Retry-After` từ server luôn được ưu tiên.)
    - `persist` → lưu trạng thái nghỉ ra `<library>/.keystate.json` để giữ qua các
      lần khởi động trong ngày (chỉ lưu id ẩn danh, không lưu key thật).
    """

    cooldown_sec: int = 0
    persist: bool = True


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
    key_rotation: KeyRotationConfig = Field(default_factory=KeyRotationConfig)
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
        key_rotation=KeyRotationConfig(**data.get("key_rotation", {})),
        rate_limits=data.get("rate_limits") or _default_rate_limits(),
    )


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Ghi cấu hình ra config.toml (tomllib chỉ đọc nên sinh TOML thủ công)."""
    path = path or Path("config.toml")
    lines = [
        "# Cấu hình MediaHarvester — file này do app sinh ra (tab Settings).",
        "",
        "[general]",
        f'library_root = "{config.library_root.as_posix()}"',
        f'default_quality = "{config.default_quality}"',
        "",
        "[download]",
        f"max_concurrent = {config.download.max_concurrent}",
        f"max_per_domain = {config.download.max_per_domain}",
        "",
        "[rate_limits]",
        *[f"{name} = {limit}" for name, limit in config.rate_limits.items()],
        "",
        "[dedup]",
        f"phash_threshold = {config.dedup.phash_threshold}",
        f"auto_skip_duplicates = {str(config.dedup.auto_skip_duplicates).lower()}",
        f"allow_duplicates = {str(config.dedup.allow_duplicates).lower()}",
        "",
        "[anti_block]",
        f"honor_robots_txt = {str(config.anti_block.honor_robots_txt).lower()}",
        "",
        "[key_rotation]",
        f"cooldown_sec = {config.key_rotation.cooldown_sec}",
        f"persist = {str(config.key_rotation.persist).lower()}",
        "",
        "[ytdlp]",
    ]
    if config.ytdlp.cookies_from_browser:
        lines.append(f'cookies_from_browser = "{config.ytdlp.cookies_from_browser}"')
    else:
        lines.append('# cookies_from_browser = "chrome"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def save_api_keys(keys: ApiKeys, path: Path | None = None) -> Path:
    """Ghi API keys ra .env (không bao giờ lưu key ở nơi khác)."""
    path = path or Path(".env")
    path.write_text(
        f"PEXELS_API_KEY={keys.pexels_api_key}\n"
        f"PIXABAY_API_KEY={keys.pixabay_api_key}\n"
        f"UNSPLASH_ACCESS_KEY={keys.unsplash_access_key}\n",
        encoding="utf-8",
    )
    return path
