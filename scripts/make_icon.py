"""Sinh icon app (assets/icon.ico) bằng Pillow — nền gradient + nút play + khung ảnh."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def make_base(size: int = 256) -> Image.Image:
    """Vẽ icon 256×256: nền xanh gradient, khung ảnh trắng, nút play xanh lá."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Nền bo góc, gradient dọc xanh đậm → xanh dương
    radius = size // 6
    for y in range(size):
        t = y / size
        color = (
            int(16 + t * 30),   # R
            int(42 + t * 70),   # G
            int(90 + t * 110),  # B
            255,
        )
        draw.line([(0, y), (size, y)], fill=color)
    # Bo góc bằng mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    img.putalpha(mask)

    draw = ImageDraw.Draw(img)
    # Khung "ảnh" trắng nghiêng nhẹ phía sau
    pad = size // 5
    draw.rounded_rectangle(
        [pad - size // 16, pad, size - pad - size // 16, size - pad],
        size // 20,
        outline=(255, 255, 255, 230),
        width=max(2, size // 32),
    )
    # Núi + mặt trời trong khung (biểu tượng media)
    draw.ellipse(
        [pad + size // 12, pad + size // 12, pad + size // 5, pad + size // 5],
        fill=(255, 214, 90, 255),
    )
    # Nút play xanh lá đè góc phải dưới
    play_center = (size - pad - size // 24, size - pad - size // 24)
    play_radius = size // 5
    draw.ellipse(
        [
            play_center[0] - play_radius, play_center[1] - play_radius,
            play_center[0] + play_radius, play_center[1] + play_radius,
        ],
        fill=(46, 194, 126, 255),
    )
    tri = play_radius // 2
    draw.polygon(
        [
            (play_center[0] - tri // 2, play_center[1] - tri),
            (play_center[0] - tri // 2, play_center[1] + tri),
            (play_center[0] + tri, play_center[1]),
        ],
        fill=(255, 255, 255, 255),
    )
    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    base = make_base(256)
    ico_path = ASSETS / "icon.ico"
    base.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    base.save(ASSETS / "icon.png")
    print(f"Đã sinh icon: {ico_path}")


if __name__ == "__main__":
    main()
