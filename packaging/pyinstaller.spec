# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec cho MediaHarvester (bản dev/test).

Build:  uv run pyinstaller packaging/pyinstaller.spec --noconfirm
Output: dist/MediaHarvester/MediaHarvester.exe (+ mediaharvester-cli.exe)

Bundle: vendor/ (ffmpeg, ffprobe, yt-dlp, deno, gallery-dl), icon,
config.toml.example, .env.example. Bản release dùng Nuitka — xem docs/BUILD.md.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # noqa: F821 — SPECPATH do PyInstaller cung cấp

datas: list = []
binaries: list = []
hiddenimports: list = ["qasync"]

# yt_dlp cần data (EJS scripts); curl_cffi/selectolax có binary riêng
for package in ("yt_dlp", "yt_dlp_ejs", "curl_cffi", "ddgs", "selectolax"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# Vendor binaries + file mẫu cấu hình đặt cạnh exe
datas += [
    (str(ROOT / "vendor"), "vendor"),
    (str(ROOT / "config.toml.example"), "."),
    (str(ROOT / ".env.example"), "."),
]

icon_path = str(ROOT / "assets" / "icon.ico")

gui_analysis = Analysis(  # noqa: F821
    [str(ROOT / "src" / "mediaharvester" / "app.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
gui_pyz = PYZ(gui_analysis.pure)  # noqa: F821

gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MediaHarvester",
    icon=icon_path,
    console=False,  # GUI app — không hiện cửa sổ console
    upx=False,
)

cli_analysis = Analysis(  # noqa: F821
    [str(ROOT / "src" / "mediaharvester" / "cli.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "PySide6", "qasync"],
    noarchive=False,
)
cli_pyz = PYZ(cli_analysis.pure)  # noqa: F821

cli_exe = EXE(  # noqa: F821
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="mediaharvester-cli",
    icon=icon_path,
    console=True,
    upx=False,
)

COLLECT(  # noqa: F821
    gui_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    cli_exe,
    cli_analysis.binaries,
    cli_analysis.datas,
    name="MediaHarvester",
    upx=False,
)
