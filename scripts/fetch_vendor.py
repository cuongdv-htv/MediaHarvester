"""Tải ffmpeg.exe + ffprobe.exe + yt-dlp.exe vào vendor/.

Chạy:
    uv run python scripts/fetch_vendor.py [--force]

- ffmpeg: bản release-essentials từ gyan.dev (zip, giải nén lấy ffmpeg/ffprobe).
- yt-dlp.exe: bản mới nhất từ GitHub releases (phục vụ nút self-update trong app).
Đã có file thì bỏ qua, trừ khi --force.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

# Ép console UTF-8 để in tiếng Việt trên Windows (cp1252)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
DENO_URL = (
    "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
)
VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor"


def download(url: str, dest: Path, label: str) -> None:
    """Tải file có in tiến độ phần trăm."""
    print(f"Đang tải {label}: {url}")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        last_pct = -1
        with dest.open("wb") as f:
            for chunk in resp.iter_bytes(1024 * 256):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    if pct // 10 > last_pct // 10:
                        last_pct = pct
                        print(f"  {label}: {pct}% ({done / 1e6:.0f}/{total / 1e6:.0f} MB)")
    print(f"  {label}: xong ({dest.stat().st_size / 1e6:.1f} MB)")


def fetch_ffmpeg(force: bool) -> None:
    """Tải zip ffmpeg essentials rồi giải nén ffmpeg.exe + ffprobe.exe vào vendor/."""
    targets = [VENDOR_DIR / "ffmpeg.exe", VENDOR_DIR / "ffprobe.exe"]
    if not force and all(t.exists() for t in targets):
        print("ffmpeg.exe + ffprobe.exe đã có trong vendor/ — bỏ qua (dùng --force để tải lại).")
        return
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"
        download(FFMPEG_URL, zip_path, "ffmpeg")
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                name = member.rsplit("/", 1)[-1]
                if name in ("ffmpeg.exe", "ffprobe.exe"):
                    target = VENDOR_DIR / name
                    with zf.open(member) as src, target.open("wb") as dst:
                        dst.write(src.read())
                    print(f"  Đã giải nén: {target}")


def fetch_ytdlp(force: bool) -> None:
    """Tải yt-dlp.exe (dùng cho nút self-update; app dùng thư viện Python)."""
    target = VENDOR_DIR / "yt-dlp.exe"
    if not force and target.exists():
        print("yt-dlp.exe đã có trong vendor/ — bỏ qua (dùng --force để tải lại).")
        return
    download(YTDLP_URL, target, "yt-dlp.exe")


def fetch_deno(force: bool) -> None:
    """Tải deno.exe — JS runtime yt-dlp cần để YouTube trả URL stream ổn định."""
    target = VENDOR_DIR / "deno.exe"
    if not force and target.exists():
        print("deno.exe đã có trong vendor/ — bỏ qua (dùng --force để tải lại).")
        return
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "deno.zip"
        download(DENO_URL, zip_path, "deno")
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open("deno.exe") as src, target.open("wb") as dst:
                dst.write(src.read())
        print(f"  Đã giải nén: {target}")


def main() -> int:
    """Tải toàn bộ vendor binaries."""
    parser = argparse.ArgumentParser(description="Tải ffmpeg + yt-dlp + deno vào vendor/")
    parser.add_argument("--force", action="store_true", help="Tải lại kể cả khi đã có")
    args = parser.parse_args()

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fetch_ffmpeg(args.force)
        fetch_ytdlp(args.force)
        fetch_deno(args.force)
    except httpx.HTTPError as exc:
        print(f"✘ Lỗi mạng khi tải vendor: {exc}")
        return 1
    print("✔ Vendor đã sẵn sàng:", ", ".join(p.name for p in VENDOR_DIR.glob("*.exe")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
