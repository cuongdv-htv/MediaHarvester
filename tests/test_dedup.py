"""Test cho core.dedup: sha256 + pHash + hamming distance."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image

from mediaharvester.core.dedup import hamming_distance, phash_image, sha256_file


def _random_block_image(path: Path, seed: int, size: int = 64, cell: int = 8) -> Path:
    """Ảnh khối xám ngẫu nhiên (seed cố định) — cấu trúc tần số thấp rõ ràng cho pHash."""
    rng = random.Random(seed)
    img = Image.new("L", (size, size))
    for bx in range(size // cell):
        for by in range(size // cell):
            value = rng.randint(0, 255)
            for x in range(bx * cell, (bx + 1) * cell):
                for y in range(by * cell, (by + 1) * cell):
                    img.putpixel((x, y), value)
    img.save(path)
    return path


def test_sha256_identical_files(tmp_path: Path) -> None:
    """Hai file nội dung giống nhau → sha256 giống nhau."""
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"noi dung giong nhau" * 100)
    b.write_bytes(b"noi dung giong nhau" * 100)
    assert sha256_file(a) == sha256_file(b)


def test_sha256_different_files(tmp_path: Path) -> None:
    """Nội dung khác → sha256 khác."""
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"noi dung A")
    b.write_bytes(b"noi dung B")
    assert sha256_file(a) != sha256_file(b)


def test_phash_same_image_recompressed(tmp_path: Path) -> None:
    """Cùng một ảnh, nén JPEG lại → pHash gần nhau (hamming ≤ 5)."""
    png = _random_block_image(tmp_path / "orig.png", seed=42)
    with Image.open(png) as img:
        img.convert("RGB").save(tmp_path / "recompressed.jpg", "JPEG", quality=60)
    h1 = phash_image(png)
    h2 = phash_image(tmp_path / "recompressed.jpg")
    assert h1 is not None and h2 is not None
    assert hamming_distance(h1, h2) <= 5


def test_phash_different_images(tmp_path: Path) -> None:
    """Hai ảnh khối ngẫu nhiên seed khác nhau → hamming lớn hơn threshold."""
    img_a = _random_block_image(tmp_path / "a.png", seed=42)
    img_b = _random_block_image(tmp_path / "b.png", seed=1337)
    h1 = phash_image(img_a)
    h2 = phash_image(img_b)
    assert h1 is not None and h2 is not None
    assert hamming_distance(h1, h2) > 5


def test_phash_broken_file_returns_none(tmp_path: Path) -> None:
    """File không phải ảnh → None, không raise."""
    bad = tmp_path / "khong-phai-anh.png"
    bad.write_bytes(b"day khong phai la anh")
    assert phash_image(bad) is None
