"""Organizer: đặt tên file, cây thư mục, sidecar metadata .json.

Quy tắc đường dẫn:
    {library_root}/{project}/{media_type}/{keyword_slug}/{provider}_{title_slug}_{shortid}.{ext}

`shortid` sinh từ hash của download URL → deterministic: chạy lại cùng URL ra
cùng tên file, nhờ đó resume `.part` giữa các lần chạy hoạt động được.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 50) -> str:
    """Chuyển chuỗi (có dấu tiếng Việt) thành slug ASCII an toàn cho tên file."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "media"


def short_id(url: str) -> str:
    """ID ngắn 8 ký tự, deterministic theo download URL."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


def ext_from_url(url: str, default: str) -> str:
    """Lấy phần mở rộng file từ URL (bỏ query string); không có thì dùng `default`."""
    suffix = PurePosixPath(urlparse(url).path).suffix.lower()
    return suffix if suffix else default


def build_asset_dir(library_root: Path, project: str, media_type: str, keyword: str) -> Path:
    """Thư mục chứa asset theo quy tắc {library_root}/{project}/{media_type}/{keyword_slug}."""
    return library_root / slugify(project) / media_type / slugify(keyword)


def build_filename(provider: str, title: str, ext: str, url: str) -> str:
    """Tên file: {provider}_{title_slug}_{shortid}{ext}."""
    return f"{provider}_{slugify(title, max_len=40)}_{short_id(url)}{ext}"


def write_sidecar(file_path: Path, metadata: dict) -> Path:
    """Ghi sidecar `{filename}.meta.json` cạnh file media (UTF-8, giữ nguyên tiếng Việt)."""
    sidecar = file_path.with_name(file_path.name + ".meta.json")
    sidecar.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return sidecar
