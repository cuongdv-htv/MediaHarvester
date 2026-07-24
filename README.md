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
  - **Xoay vòng nhiều key**: điền nhiều key cách nhau bởi dấu phẩy
    (vd `PEXELS_API_KEY=key1,key2,key3`) — khi 1 key chạm giới hạn free trong ngày
    app tự đổi sang key kế tiếp. Trong GUI (tab Cài đặt) nhập mỗi dòng 1 key.
    Chỉnh hành vi nghỉ ở mục `[key_rotation]` trong `config.toml`.
- Copy `config.toml.example` → `config.toml` và chỉnh thư mục thư viện, số luồng tải...

## Đóng gói thành .exe

Xem [docs/BUILD.md](docs/BUILD.md) — PyInstaller (dev) / Nuitka (release) + Inno Setup.

## Nguồn media (9 providers)

pexels, pixabay, unsplash, openverse, wikimedia, nasa, ddgs (DuckDuckGo),
gallerydl (gallery MXH), ytdlp (YouTube/TikTok/X...), scraper (URL trang bất kỳ).
