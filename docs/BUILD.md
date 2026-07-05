# Hướng dẫn build MediaHarvester thành .exe

## Chuẩn bị (một lần)

```powershell
# 1. Cài dependencies
uv sync

# 2. Tải vendor binaries (ffmpeg, ffprobe, yt-dlp, deno, gallery-dl — ~280 MB)
uv run python scripts/fetch_vendor.py

# 3. (Tùy chọn) Sinh lại icon nếu đổi thiết kế
uv run python scripts/make_icon.py
```

## Build dev — PyInstaller (onedir, nhanh)

```powershell
uv run pyinstaller packaging/pyinstaller.spec --noconfirm
```

Kết quả: `dist/MediaHarvester/`
- `MediaHarvester.exe` — GUI (không console)
- `mediaharvester-cli.exe` — CLI
- `vendor/` — ffmpeg + yt-dlp + deno + gallery-dl đi kèm
- `config.toml.example`, `.env.example` — copy bỏ đuôi `.example` rồi điền

Chạy thử ngay: `dist\MediaHarvester\MediaHarvester.exe`

Lưu ý: app đọc `config.toml` / `.env` / thư mục `library/` **cạnh file exe**
(khi chạy frozen, `app_dir()` = thư mục chứa exe).

## Build release — Nuitka (khởi động nhanh hơn, khó decompile)

```powershell
uv add --dev nuitka
uv run nuitka `
  --standalone `
  --enable-plugin=pyside6 `
  --windows-console-mode=disable `
  --windows-icon-from-ico=assets/icon.ico `
  --include-data-dir=vendor=vendor `
  --include-data-files=config.toml.example=config.toml.example `
  --include-data-files=.env.example=.env.example `
  --include-package-data=yt_dlp `
  --include-package-data=yt_dlp_ejs `
  --output-dir=build-nuitka `
  --output-filename=MediaHarvester.exe `
  src/mediaharvester/app.py
```

Kết quả trong `build-nuitka/app.dist/` — đổi tên thư mục thành `MediaHarvester`
rồi copy vào `dist/` trước khi đóng installer.

> ⚠️ **Lưu ý Nuitka + yt-dlp**: yt-dlp gộp hàng nghìn extractor thành một file C
> khổng lồ (`yt_dlp.extractor.lazy_extractors`). Compiler **MinGW** (Nuitka tự tải)
> thường **hết bộ nhớ (`cc1.exe: out of memory`)** khi compile file này, và còn
> vấp lỗi header `structuredquerycondition.h`. **Bắt buộc dùng MSVC** để build Nuitka:
>
> 1. Cài Visual Studio Build Tools (workload "Desktop development with C++"):
>    `winget install Microsoft.VisualStudio.2022.BuildTools`
> 2. Thêm `--msvc=latest` vào lệnh Nuitka ở trên (bỏ MinGW).
> 3. Nếu vẫn thiếu bộ nhớ, thêm `--low-memory --jobs=2`.
>
> Bản release chính thức v0.1.0 build bằng **PyInstaller** (ổn định, không cần MSVC).

## Đóng installer — Inno Setup

1. Cài [Inno Setup 6](https://jrsoftware.org/isinfo.php)
   (`winget install JRSoftware.InnoSetup`).
2. Build xong `dist/MediaHarvester/` (PyInstaller hoặc Nuitka).
3. Compile (đường dẫn ISCC.exe tùy nơi cài — winget đặt ở `%LOCALAPPDATA%\Programs`):

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Kết quả: `dist/MediaHarvester-Setup-0.1.0.exe`.

## Checklist test trên máy Windows sạch (không có Python)

1. Chạy installer → mở app từ Start Menu.
2. Tab Cài đặt: điền API key Pexels/Pixabay → Lưu → Health-check providers.
3. Tab Tìm kiếm: search 1 từ khóa → tick vài ảnh → thêm hàng đợi → tải xong.
4. Tab Thư viện: thấy asset + thumbnail; Export CSV chạy được.
5. Dán 1 URL YouTube → tải video (yt-dlp + ffmpeg + deno bundle hoạt động).
