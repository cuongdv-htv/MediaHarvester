"""SQLModel: Project, Asset, DownloadJob — schema SQLite của MediaHarvester."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    """Thời điểm hiện tại (UTC, timezone-aware)."""
    return datetime.now(UTC)


class Project(SQLModel, table=True):
    """Một project edit video — gom nhóm các asset tải về."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=_now)


class Asset(SQLModel, table=True):
    """Một file media đã tải về, kèm metadata nguồn gốc + license."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    file_path: str
    media_type: str = Field(index=True)  # "image" | "video"
    provider: str = Field(index=True)
    source_url: str
    source_page_url: str
    license: str
    author: str | None = None
    title: str
    keywords: str = ""  # CSV các từ khóa tìm kiếm
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    filesize: int | None = None
    sha256: str | None = Field(default=None, unique=True, index=True)
    phash: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_now)


class DownloadJob(SQLModel, table=True):
    """Một job tải xuống trong queue — lưu trạng thái + lỗi để truy vết."""

    id: int | None = Field(default=None, primary_key=True)
    asset_id: int | None = Field(default=None, foreign_key="asset.id")
    url: str
    status: str = "queued"  # queued|downloading|processing|done|failed|skipped_duplicate|cancelled
    error_msg: str | None = None
    retries: int = 0
    created_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
