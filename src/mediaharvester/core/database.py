"""Engine, session và migration đơn giản cho SQLite."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from mediaharvester.core import models  # noqa: F401 — import để đăng ký bảng vào metadata
from mediaharvester.core.models import Project


def get_engine(db_path: Path) -> Engine:
    """Tạo engine SQLite tại `db_path` (tự tạo thư mục cha nếu chưa có)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(engine: Engine) -> None:
    """Migration đơn giản: tạo tất cả bảng nếu chưa tồn tại."""
    SQLModel.metadata.create_all(engine)
    logger.debug("Database đã sẵn sàng: {}", engine.url)


def get_session(engine: Engine) -> Session:
    """Mở một session mới — caller dùng `with get_session(engine) as s:`."""
    return Session(engine)


def get_or_create_project(session: Session, name: str) -> Project:
    """Lấy project theo tên, chưa có thì tạo mới."""
    project = session.exec(select(Project).where(Project.name == name)).first()
    if project is None:
        project = Project(name=name)
        session.add(project)
        session.commit()
        session.refresh(project)
        logger.info("Đã tạo project mới: {}", name)
    return project
