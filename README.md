# MediaHarvester

App desktop Windows giúp editor video tìm kiếm + tải hàng loạt ảnh/video từ nhiều
nguồn internet làm tài nguyên edit video (kinh tế, khoa học, công nghệ, địa chính trị).

## Chạy dev

```powershell
uv sync
uv run mediaharvester-cli --help
uv run pytest
```

## Chạy GUI

```powershell
uv run python scripts/fetch_vendor.py   # tải ffmpeg/yt-dlp/deno/gallery-dl (một lần)
uv run mediaharvester
```

## Cấu hình

- Copy `.env.example` → `.env` và điền API keys (Pexels, Pixabay, Unsplash).
- Copy `config.toml.example` → `config.toml` và chỉnh thư mục thư viện, số luồng tải...

## Đóng gói thành .exe

Xem [docs/BUILD.md](docs/BUILD.md) — PyInstaller (dev) / Nuitka (release) + Inno Setup.

## Nguồn media (9 providers)

pexels, pixabay, unsplash, openverse, wikimedia, nasa, ddgs (DuckDuckGo),
gallerydl (gallery MXH), ytdlp (YouTube/TikTok/X...), scraper (URL trang bất kỳ).
