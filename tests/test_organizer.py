"""Test cho core.organizer: slugify, đường dẫn, tên file, sidecar."""

from __future__ import annotations

import json
from pathlib import Path

from mediaharvester.core.organizer import (
    build_asset_dir,
    build_filename,
    ext_from_url,
    short_id,
    slugify,
    write_sidecar,
)


def test_slugify_vietnamese() -> None:
    """Tiếng Việt có dấu → slug ASCII."""
    assert slugify("Tấm pin mặt trời") == "tam-pin-mat-troi"
    assert slugify("Đường sắt đô thị") == "duong-sat-do-thi"


def test_slugify_special_chars_and_empty() -> None:
    """Ký tự đặc biệt bị thay bằng '-', chuỗi rỗng có fallback."""
    assert slugify("Solar Panel (4K) — HD!") == "solar-panel-4k-hd"
    assert slugify("???") == "media"


def test_slugify_max_len() -> None:
    """Slug bị cắt theo max_len, không kết thúc bằng '-'."""
    slug = slugify("a b " * 50, max_len=10)
    assert len(slug) <= 10
    assert not slug.endswith("-")


def test_short_id_deterministic() -> None:
    """Cùng URL → cùng shortid (phục vụ resume); URL khác → id khác."""
    url = "https://example.com/file.jpg"
    assert short_id(url) == short_id(url)
    assert len(short_id(url)) == 8
    assert short_id(url) != short_id(url + "?v=2")


def test_ext_from_url() -> None:
    """Lấy ext từ URL, bỏ query string; không có ext → default."""
    assert ext_from_url("https://x.com/a/b/photo.JPEG?w=1080", ".jpg") == ".jpeg"
    assert ext_from_url("https://x.com/download", ".mp4") == ".mp4"


def test_build_asset_dir() -> None:
    """Cây thư mục đúng quy tắc {root}/{project}/{type}/{keyword_slug}."""
    path = build_asset_dir(Path("lib"), "Dự án Demo", "image", "tấm pin")
    assert path == Path("lib") / "du-an-demo" / "image" / "tam-pin"


def test_build_filename() -> None:
    """Tên file: {provider}_{title_slug}_{shortid}{ext}."""
    url = "https://example.com/x.jpg"
    name = build_filename("pexels", "Solar Panel HD", ".jpg", url)
    assert name == f"pexels_solar-panel-hd_{short_id(url)}.jpg"


def test_write_sidecar(tmp_path: Path) -> None:
    """Sidecar {filename}.meta.json ghi đúng UTF-8, giữ tiếng Việt."""
    media = tmp_path / "photo.jpg"
    media.write_bytes(b"fake")
    sidecar = write_sidecar(media, {"title": "Tấm pin mặt trời", "license": "CC0"})
    assert sidecar.name == "photo.jpg.meta.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["title"] == "Tấm pin mặt trời"
