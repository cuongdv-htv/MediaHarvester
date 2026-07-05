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

## Đóng installer — Inno Setup

1. Cài [Inno Setup 6](https://jrsoftware.org/isinfo.php).
2. Build xong `dist/MediaHarvester/` (PyInstaller hoặc Nuitka).
3. Compile:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Kết quả: `dist/MediaHarvester-Setup-0.1.0.exe`.

## Checklist test trên máy Windows sạch (không có Python)

1. Chạy installer → mở app từ Start Menu.
2. Tab Cài đặt: điền API key Pexels/Pixabay → Lưu → Health-check providers.
3. Tab Tìm kiếm: search 1 từ khóa → tick vài ảnh → thêm hàng đợi → tải xong.
4. Tab Thư viện: thấy asset + thumbnail; Export CSV chạy được.
5. Dán 1 URL YouTube → tải video (yt-dlp + ffmpeg + deno bundle hoạt động).
