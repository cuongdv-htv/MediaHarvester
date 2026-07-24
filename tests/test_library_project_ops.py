"""Test thao tác theo project ở tab Thư viện: copy file ra ngoài + xóa file trên đĩa."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 chưa cài")

from mediaharvester.core.models import Asset  # noqa: E402
from mediaharvester.gui.library_tab import LibraryTab  # noqa: E402


def _asset(path: Path, media_type: str = "image") -> Asset:
    """Asset tối thiểu đủ dùng cho các helper thao tác file."""
    return Asset(
        project_id=1,
        file_path=str(path),
        media_type=media_type,
        provider="pexels",
        source_url="http://x/a",
        source_page_url="http://x/p",
        license="Pexels License",
        title="anh test",
    )


def _make_library(tmp_path: Path) -> tuple[Path, list[Asset]]:
    """Dựng cây thư viện giả: 1 ảnh + 1 video, kèm sidecar và thumbnail."""
    lib = tmp_path / "library"
    img = lib / "duan" / "image" / "solar" / "a.jpg"
    vid = lib / "duan" / "video" / "solar" / "b.mp4"
    for p in (img, vid):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"noi dung " + p.name.encode())
    # Sidecar + thumbnail: KHÔNG được copy sang thư mục đích
    Path(str(img) + ".meta.json").write_text("{}", encoding="utf-8")
    thumbs = lib / ".thumbnails"
    thumbs.mkdir(parents=True, exist_ok=True)
    (thumbs / "a.jpg").write_bytes(b"thumb")
    return lib, [_asset(img), _asset(vid, "video")]


def test_copy_media_giu_cau_truc_va_bo_qua_sidecar(tmp_path) -> None:
    """Copy đúng ảnh/video, giữ cấu trúc thư mục, không kèm .meta.json."""
    lib, assets = _make_library(tmp_path)
    dest = tmp_path / "xuat"

    copied, existed, missing, failed = LibraryTab._copy_media(assets, lib, dest)

    assert (copied, existed, missing, failed) == (2, 0, 0, 0)
    assert (dest / "duan" / "image" / "solar" / "a.jpg").exists()
    assert (dest / "duan" / "video" / "solar" / "b.mp4").exists()
    # Sidecar và thumbnail không được copy
    assert not (dest / "duan" / "image" / "solar" / "a.jpg.meta.json").exists()
    assert not (dest / ".thumbnails").exists()


def test_copy_media_lan_hai_khong_copy_lai(tmp_path) -> None:
    """Copy lần hai vào cùng thư mục → nhận diện file đã có, không ghi đè."""
    lib, assets = _make_library(tmp_path)
    dest = tmp_path / "xuat"
    LibraryTab._copy_media(assets, lib, dest)

    copied, existed, missing, failed = LibraryTab._copy_media(assets, lib, dest)

    assert (copied, existed, failed) == (0, 2, 0)


def test_copy_media_khong_ghi_de_file_khac_noi_dung(tmp_path) -> None:
    """Trùng tên nhưng khác nội dung → tạo file hậu tố, giữ nguyên file cũ."""
    lib, assets = _make_library(tmp_path)
    dest = tmp_path / "xuat"
    target = dest / "duan" / "image" / "solar" / "a.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"file cua nguoi dung - khong duoc mat")

    LibraryTab._copy_media([assets[0]], lib, dest)

    assert target.read_bytes() == b"file cua nguoi dung - khong duoc mat"
    assert (dest / "duan" / "image" / "solar" / "a_2.jpg").exists()


def test_copy_media_dem_file_thieu(tmp_path) -> None:
    """File đã bị xóa khỏi đĩa → đếm vào 'missing', không làm hỏng cả lượt copy."""
    lib, assets = _make_library(tmp_path)
    Path(assets[0].file_path).unlink()

    copied, existed, missing, failed = LibraryTab._copy_media(assets, lib, tmp_path / "xuat")

    assert (copied, missing, failed) == (1, 1, 0)


def test_copy_media_nhieu_project_moi_project_mot_thu_muc(tmp_path) -> None:
    """Tải toàn bộ thư viện: mỗi project nằm gọn trong thư mục con của nó."""
    lib = tmp_path / "library"
    a = lib / "du-an-1" / "image" / "solar" / "a.jpg"
    b = lib / "du-an-2" / "video" / "wind" / "b.mp4"
    for p in (a, b):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" + p.name.encode())
    assets = [_asset(a), _asset(b, "video")]
    dest = tmp_path / "xuat"

    copied, _, missing, failed = LibraryTab._copy_media(assets, lib, dest)

    assert (copied, missing, failed) == (2, 0, 0)
    assert (dest / "du-an-1" / "image" / "solar" / "a.jpg").exists()
    assert (dest / "du-an-2" / "video" / "wind" / "b.mp4").exists()


def test_delete_files_xoa_ca_sidecar_thumbnail_va_don_thu_muc(tmp_path) -> None:
    """Xóa file media + sidecar + thumbnail rồi dọn sạch thư mục project rỗng."""
    lib, assets = _make_library(tmp_path)
    img = Path(assets[0].file_path)

    removed = LibraryTab._delete_files(assets, lib / ".thumbnails", lib / "duan")

    assert removed == 2
    assert not img.exists()
    assert not Path(str(img) + ".meta.json").exists()
    assert not (lib / ".thumbnails" / "a.jpg").exists()
    assert not (lib / "duan").exists()  # thư mục project rỗng đã được dọn


def test_delete_files_for_projects_nhieu_project(tmp_path) -> None:
    """Xóa file của nhiều project cùng lúc, cộng dồn số file đã xóa."""
    lib = tmp_path / "library"
    a = lib / "du-an-1" / "image" / "kw" / "a.jpg"
    b = lib / "du-an-2" / "image" / "kw" / "b.jpg"
    for p in (a, b):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(p.name.encode())

    removed = LibraryTab._delete_files_for_projects(
        {"du-an-1": [_asset(a)], "du-an-2": [_asset(b)]},
        lib / ".thumbnails",
        lib,
    )

    assert removed == 2
    assert not a.exists() and not b.exists()
    assert not (lib / "du-an-1").exists()
    assert not (lib / "du-an-2").exists()


def test_delete_files_giu_file_la_trong_thu_muc(tmp_path) -> None:
    """Thư mục còn file khác (người dùng tự bỏ vào) thì không bị xóa."""
    lib, assets = _make_library(tmp_path)
    la = lib / "duan" / "image" / "solar" / "ghi-chu.txt"
    la.write_text("cua toi", encoding="utf-8")

    LibraryTab._delete_files(assets, lib / ".thumbnails", lib / "duan")

    assert la.exists()
    assert (lib / "duan").exists()
