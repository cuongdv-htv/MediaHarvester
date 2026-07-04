"""Khử trùng lặp: sha256 (trùng tuyệt đối) + pHash (ảnh gần giống nhau).

Pipeline sau mỗi download:
1. sha256 trùng → xóa file mới, đánh dấu skipped_duplicate.
2. Ảnh: pHash, hamming distance ≤ threshold với asset cùng project → hỏi user
   (GUI) hoặc auto-skip (config).
3. Video: extract frame giây thứ 1 bằng ffmpeg → pHash frame.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import imagehash
from loguru import logger
from PIL import Image
from sqlmodel import Session, select

from mediaharvester.core.models import Asset
from mediaharvester.utils.ffmpeg import extract_frame

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Tính sha256 của file theo từng chunk (không load cả file vào RAM)."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def phash_image(path: Path) -> str | None:
    """pHash của một file ảnh; lỗi đọc ảnh → None (log warning, không crash)."""
    try:
        with Image.open(path) as img:
            return str(imagehash.phash(img))
    except Exception as exc:
        logger.warning("Không tính được pHash cho {}: {}", path.name, exc)
        return None


def phash_video(path: Path) -> str | None:
    """pHash frame giây thứ 1 của video (cần ffmpeg); thiếu ffmpeg → None."""
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.png"
        if not extract_frame(path, frame, at_sec=1.0):
            return None
        return phash_image(frame)


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Khoảng cách hamming giữa 2 pHash dạng hex string."""
    return imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)


def find_sha256_duplicate(session: Session, sha256: str) -> Asset | None:
    """Tìm asset đã có cùng sha256 (trùng tuyệt đối, mọi project)."""
    return session.exec(select(Asset).where(Asset.sha256 == sha256)).first()


def find_phash_duplicate(
    session: Session, project_id: int, phash: str, threshold: int = 5
) -> Asset | None:
    """Tìm asset cùng project có pHash gần giống (hamming ≤ threshold)."""
    candidates = session.exec(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.phash.is_not(None),  # type: ignore[union-attr]
        )
    ).all()
    for asset in candidates:
        if asset.phash and hamming_distance(phash, asset.phash) <= threshold:
            return asset
    return None
