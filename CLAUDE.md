
## VAI TRÒ

Bạn là senior Python engineer. Hãy xây dựng **MediaHarvester** — app desktop Windows (đóng gói .exe) giúp editor video tìm kiếm + tải hàng loạt ảnh/video từ nhiều nguồn internet làm tài nguyên edit video (chủ đề kinh tế, khoa học, công nghệ, địa chính trị).

Nguyên tắc làm việc:

1. Làm theo đúng PHASE bên dưới, mỗi phase xong phải chạy được + pass test rồi mới sang phase sau.
2. Trước khi code mỗi phase: trình bày ngắn plan → rồi implement.
3. Không tự ý đổi tech stack hoặc cấu trúc thư mục đã quy định. Nếu thấy bất hợp lý, nêu lý do và hỏi tôi trước.
4. Code có type hints đầy đủ, docstring tiếng Việt, log rõ ràng.
5. Mọi lỗi mạng/parse phải được catch và hiển thị thân thiện — app không bao giờ crash vì 1 download lỗi.

## TECH STACK (BẮT BUỘC — KHÔNG ĐỔI)

| Thành phần | Công nghệ |
|---|---|
| Ngôn ngữ | Python 3.12 |
| GUI | **PySide6** (Qt6) + **qasync** (chạy asyncio event loop chung với Qt) |
| HTTP client | **httpx** (async) + **tenacity** (retry) |
| Anti-block fallback | **curl_cffi** (chỉ dùng khi httpx bị 403) |
| Video downloader | **yt-dlp** (import như thư viện Python) |
| Gallery/ảnh MXH | **gallery-dl** (subprocess, config JSON) |
| Search ảnh không key | **duckduckgo_search (DDGS)** |
| Scrape HTML tĩnh | **selectolax** |
| Scrape trang JS | **playwright** (optional extra, lazy import) |
| Database | **SQLite** qua **SQLModel** |
| Ảnh/thumbnail | **Pillow**; dedup bằng **imagehash** (pHash) |
| Video processing | **ffmpeg** (bundle sẵn `ffmpeg.exe` trong `vendor/`) |
| Config | **pydantic-settings**, file `config.toml` + `.env` (API keys) |
| Logging | **loguru** (file xoay vòng trong `logs/`) |
| Test | **pytest** + **pytest-asyncio**, mock HTTP bằng **respx** |
| Lint/format | **ruff** |
| Đóng gói | **PyInstaller** (dev, `--onedir`) → **Nuitka** (release); installer **Inno Setup** |
| Quản lý deps | **uv** (pyproject.toml) |

## CẤU TRÚC THƯ MỤC (BẮT BUỘC)

```
mediaharvester/
├── pyproject.toml
├── config.toml.example
├── .env.example              # PEXELS_API_KEY=, PIXABAY_API_KEY=, UNSPLASH_ACCESS_KEY=
├── vendor/                   # ffmpeg.exe, yt-dlp.exe (self-update)
├── src/mediaharvester/
│   ├── app.py                # entry point GUI
│   ├── cli.py                # entry point CLI (dùng từ Phase 1)
│   ├── core/
│   │   ├── models.py         # SQLModel: Asset, Project, DownloadJob
│   │   ├── database.py       # engine, session, migration đơn giản
│   │   ├── downloader.py     # DownloadManager: queue asyncio, semaphore, retry, resume, progress callback
│   │   ├── dedup.py          # sha256 + pHash
│   │   ├── organizer.py      # đặt tên file, cây thư mục, sidecar metadata .json
│   │   ├── thumbnails.py     # Pillow (ảnh) + ffmpeg (frame video)
│   │   └── config.py         # pydantic-settings
│   ├── providers/
│   │   ├── base.py           # abstract Provider + registry (entry-point pattern)
│   │   ├── pexels.py         # ảnh + video
│   │   ├── pixabay.py        # ảnh + video
│   │   ├── unsplash.py       # ảnh
│   │   ├── openverse.py      # ảnh CC
│   │   ├── wikimedia.py      # ảnh/video Commons
│   │   ├── nasa.py           # NASA Image Library
│   │   ├── ytdlp_provider.py # video: search (ytsearchN:) + tải URL bất kỳ
│   │   ├── gallerydl_provider.py
│   │   ├── ddgs_images.py    # DuckDuckGo images
│   │   └── generic_scraper.py# selectolax + playwright fallback (Phase 5)
│   ├── gui/
│   │   ├── main_window.py    # QTabWidget: Search / Queue / Library / Settings
│   │   ├── search_tab.py
│   │   ├── queue_tab.py
│   │   ├── library_tab.py
│   │   ├── settings_tab.py
│   │   └── widgets/          # ResultCard (thumbnail grid), ProgressDelegate...
│   └── utils/                # helpers, ffmpeg wrapper, ua pool
├── tests/
├── logs/
└── packaging/
    ├── pyinstaller.spec
    └── installer.iss         # Inno Setup
```

## KIẾN TRÚC CỐT LÕI

### 1. Provider interface (mọi nguồn đều implement chuẩn này)

```python
class MediaType(StrEnum):
    IMAGE = "image"; VIDEO = "video"

@dataclass
class SearchResult:
    provider: str
    media_type: MediaType
    title: str
    thumbnail_url: str
    download_url: str          # hoặc page_url nếu cần resolve (yt-dlp)
    source_page_url: str
    license: str               # "Pexels License", "CC0", "unknown"...
    author: str | None
    width: int | None
    height: int | None
    duration_sec: float | None # video
    extra: dict                # provider-specific

class Provider(ABC):
    name: str
    supported_types: set[MediaType]
    requires_api_key: bool

    @abstractmethod
    async def search(self, query: str, media_type: MediaType,
                     page: int = 1, per_page: int = 30) -> list[SearchResult]: ...
    @abstractmethod
    async def download(self, result: SearchResult, dest_dir: Path,
                       progress_cb: Callable[[int, int], None],
                       quality: str = "1080p") -> Path: ...
    async def health_check(self) -> bool: ...   # kiểm tra key/kết nối
```

Registry tự động: provider tự đăng ký qua decorator `@register_provider`; GUI đọc registry để render checkbox nguồn. Thêm nguồn mới = thêm 1 file, không sửa core.

### 2. DownloadManager (core/downloader.py)

- Queue `asyncio.Queue`, worker pool với `Semaphore` — mặc định 4 concurrent tổng, **tối đa 2/domain** (dict semaphore theo domain).
- Retry: tenacity, exponential backoff, tối đa 3 lần; lỗi 429 thì đọc `Retry-After`.
- Resume: tải file lớn bằng stream vào `*.part` + header `Range` khi tải lại; xong rename.
- Rate limit theo provider: đọc config `rate_limits` (Pexels 200/h, Unsplash 50/h...), dùng token-bucket đơn giản; hiển thị quota còn lại lên GUI.
- Mỗi job phát progress qua callback → GUI signal. Trạng thái job: queued → downloading → processing (dedup/thumbnail) → done | failed | skipped_duplicate.
- Pause/Resume/Cancel từng job và toàn queue.

### 3. Database schema (SQLModel)

```
Project(id, name, created_at)
Asset(id, project_id FK, file_path, media_type, provider, source_url,
      source_page_url, license, author, title, keywords TEXT(csv),
      width, height, duration_sec, filesize, sha256 UNIQUE-nullable,
      phash, created_at)
DownloadJob(id, asset_id nullable, url, status, error_msg, retries,
            created_at, finished_at)
```

### 4. Dedup pipeline (chạy sau mỗi download)

1. sha256 trùng → xóa file mới, đánh dấu `skipped_duplicate`.
2. Ảnh: pHash, hamming distance ≤ 5 với asset cùng project → hỏi user (GUI) hoặc auto-skip (config).
3. Video: extract frame giây thứ 1 bằng ffmpeg → pHash frame.

### 5. Organizer — quy tắc file

- Đường dẫn: `{library_root}/{project}/{media_type}/{keyword_slug}/{provider}_{title_slug}_{shortid}.{ext}`
- Mỗi file có sidecar `{filename}.meta.json` chứa toàn bộ metadata + license + URL nguồn (phục vụ đối chiếu bản quyền).

### 6. GUI — quy tắc bắt buộc

- **Không bao giờ block UI thread**: mọi I/O qua asyncio (qasync); progress cập nhật qua Qt Signals.
- **Search tab**: ô query (hỗ trợ nhiều từ khóa, mỗi dòng 1 keyword), checkbox chọn providers, chọn image/video/cả hai, min resolution, nút Search → grid thumbnail (lazy load ảnh thumb qua httpx, cache đĩa) → tick chọn → "Add to Queue". Có ô dán URL trực tiếp (YouTube/TikTok/X...) → route sang yt-dlp provider.
- **Queue tab**: bảng jobs, progress bar per-row, tốc độ, pause/cancel, tổng quota API còn lại.
- **Library tab**: duyệt asset theo project/keyword/provider/type, thumbnail grid, search text, double-click mở file, chuột phải: mở thư mục / copy đường dẫn / xóa / xem metadata. Nút "Export danh sách nguồn" → CSV (phục vụ ghi credit).
- **Settings tab**: API keys (lưu `.env`), thư mục thư viện, concurrent, chất lượng mặc định, ngôn ngữ UI **tiếng Việt** (hardcode tiếng Việt, không cần i18n framework), nút "Update yt-dlp" (chạy `vendor/yt-dlp.exe -U`), nút health-check tất cả providers.

### 7. yt-dlp provider — yêu cầu cụ thể

- Search: `ytsearch{n}:{query}` lấy metadata (không tải) → map thành SearchResult (thumbnail, duration, title).
- Download: format `bestvideo[height<=?][ext=mp4]+bestaudio[ext=m4a]/best`, ưu tiên h264; option cắt đoạn `download_ranges` nhập từ GUI (hh:mm:ss-hh:mm:ss); `writeinfojson`; progress hook → callback chuẩn của DownloadManager.
- ffmpeg location trỏ tới `vendor/ffmpeg.exe`.
- Hỗ trợ cookies-from-browser (config chọn chrome/edge/firefox) cho X/Instagram.

### 8. Anti-block (chỉ cho ddgs/generic_scraper)

- UA pool thật, delay ngẫu nhiên 1–3s/request/domain, honor robots.txt (cấu hình override được), fallback `curl_cffi` impersonate="chrome" khi gặp 403/blocked.

## PHASES — LÀM THEO THỨ TỰ

### Phase 0 — Skeleton
Khởi tạo repo: pyproject (uv), ruff, pytest, cấu trúc thư mục đầy đủ (file rỗng/stub), config + logging chạy được, `cli.py --version` chạy OK.
**Nghiệm thu**: `uv run pytest` pass, `uv run mediaharvester-cli --help` hiện help.

### Phase 1 — Core + 2 provider stock + CLI
models/database/downloader/dedup/organizer + providers pexels, pixabay.
CLI: `mediaharvester-cli search "solar panel" --type video --providers pexels,pixabay --limit 20 --download --project demo`.
**Nghiệm thu**: tải thật ≥10 file về đúng cấu trúc thư mục, SQLite có record, chạy lại lệnh → skip duplicates. Unit test cho dedup, organizer, retry (mock respx).

### Phase 2 — yt-dlp provider
Search YouTube + tải URL bất kỳ + cắt đoạn + progress. Bundle hướng dẫn tải ffmpeg vào `vendor/` (viết script `scripts/fetch_vendor.py` tự tải ffmpeg + yt-dlp.exe).
**Nghiệm thu**: CLI tải được 1 video YouTube 1080p, 1 đoạn cắt 30s, metadata json sinh ra.

### Phase 3 — GUI đầy đủ
4 tab như spec mục 6, nối với core qua qasync.
**Nghiệm thu**: search đa nguồn → tick → queue → tải song song có progress → asset xuất hiện trong Library kèm thumbnail; UI không đơ khi tải 10 file.

### Phase 4 — Providers mở rộng
unsplash, openverse, wikimedia, nasa, ddgs_images, gallerydl_provider. Health-check trong Settings.
**Nghiệm thu**: mỗi provider có integration test (skip nếu thiếu key) + search được từ GUI.

### Phase 5 — Nâng cao + đóng gói
- generic_scraper (nhập URL trang bất kỳ → liệt kê ảnh/video tìm được → chọn tải; playwright fallback).
- Tính năng "Kịch bản → từ khóa": paste kịch bản, tách keywords bằng regex/heuristic (danh từ, cụm 2-3 từ, loại stopwords tiếng Việt + Anh) → đổ vào Search tab. (Chừa interface `KeywordExtractor` để sau này thay bằng LLM API.)
- PyInstaller onedir spec (bundle vendor/, icon) + installer.iss. Viết `docs/BUILD.md` hướng dẫn build exe + build Nuitka cho release.
**Nghiệm thu**: file .exe chạy trên máy Windows sạch không có Python.

## KHÔNG ĐƯỢC LÀM

- Không dùng Selenium, Scrapy, threading thô (chỉ asyncio + qasync).
- Không gọi yt-dlp bằng subprocess trong core (trừ self-update); dùng import.
- Không lưu API key trong code hoặc SQLite — chỉ `.env`.
- Không tải lại thumbnail đã cache; không giữ toàn bộ ảnh trong RAM (dùng QPixmapCache giới hạn).
- Không nuốt exception im lặng — log đầy đủ + hiện toast/statusbar cho user.
- Không thêm tính năng ngoài spec khi chưa hỏi.

