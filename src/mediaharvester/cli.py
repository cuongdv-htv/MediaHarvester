"""Entry point CLI của MediaHarvester.

Ví dụ:
    mediaharvester-cli search "solar panel" --type video \\
        --providers pexels,pixabay --limit 20 --download --project demo
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from itertools import zip_longest
from urllib.parse import urlparse

import httpx
from loguru import logger

from mediaharvester import __version__
from mediaharvester.core.config import ApiKeys, AppConfig, load_config
from mediaharvester.core.database import get_engine, init_db
from mediaharvester.core.downloader import DownloadManager, JobState, JobStatus
from mediaharvester.providers.base import MediaType, Provider, SearchResult, get_registry
from mediaharvester.utils.logging_setup import setup_logging


def _force_utf8_console() -> None:
    """Ép stdout/stderr sang UTF-8 để in được tiếng Việt trên console Windows (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    """Tạo argument parser cho CLI."""
    parser = argparse.ArgumentParser(
        prog="mediaharvester-cli",
        description=(
            "MediaHarvester — tìm kiếm & tải hàng loạt ảnh/video từ nhiều nguồn "
            "internet làm tài nguyên edit video."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command")
    sp = sub.add_parser("search", help="Tìm kiếm media từ các providers")
    sp.add_argument("query", help="Từ khóa tìm kiếm")
    sp.add_argument(
        "--type", choices=["image", "video", "both"], default="image", dest="media_type",
        help="Loại media (mặc định: image)",
    )
    sp.add_argument(
        "--providers", default="pexels,pixabay",
        help="Danh sách provider, phân cách bằng dấu phẩy (mặc định: pexels,pixabay)",
    )
    sp.add_argument("--limit", type=int, default=20, help="Số kết quả tối đa (mặc định: 20)")
    sp.add_argument("--download", action="store_true", help="Tải các kết quả về máy")
    sp.add_argument("--project", default="default", help="Tên project (mặc định: default)")

    dp = sub.add_parser("download", help="Tải video từ URL bất kỳ qua yt-dlp (YouTube/TikTok/X...)")
    dp.add_argument("url", help="URL video cần tải")
    dp.add_argument(
        "--clip", default=None,
        help="Cắt đoạn hh:mm:ss-hh:mm:ss, ví dụ 00:01:00-00:01:30",
    )
    dp.add_argument("--project", default="default", help="Tên project (mặc định: default)")
    return parser


def _build_providers(
    names: list[str], keys: ApiKeys, client: httpx.AsyncClient, config: AppConfig
) -> dict[str, Provider]:
    """Khởi tạo các provider được chọn; thiếu key/không tồn tại → cảnh báo, bỏ qua."""
    # Import để trigger @register_provider
    from mediaharvester.providers import pexels, pixabay, ytdlp_provider  # noqa: F401

    registry = get_registry()
    key_map = {
        "pexels": keys.pexels_api_key,
        "pixabay": keys.pixabay_api_key,
        "unsplash": keys.unsplash_access_key,
    }
    providers: dict[str, Provider] = {}
    for name in names:
        cls = registry.get(name)
        if cls is None:
            print(f"⚠ Provider '{name}' không tồn tại — bỏ qua. Khả dụng: {sorted(registry)}")
            continue
        api_key = key_map.get(name, "")
        if cls.requires_api_key and not api_key:
            print(f"⚠ Thiếu API key cho '{name}' trong .env — bỏ qua.")
            continue
        if name == "ytdlp":
            providers[name] = cls(cookies_from_browser=config.ytdlp.cookies_from_browser)
        else:
            providers[name] = cls(api_key=api_key, client=client)
    return providers


def _interleave(groups: list[list[SearchResult]]) -> list[SearchResult]:
    """Trộn xen kẽ kết quả từ nhiều provider cho công bằng."""
    merged: list[SearchResult] = []
    for bundle in zip_longest(*groups):
        merged.extend(r for r in bundle if r is not None)
    return merged


def _print_results(results: list[SearchResult]) -> None:
    """In danh sách kết quả dạng bảng gọn."""
    print(f"\nTìm thấy {len(results)} kết quả:")
    for i, r in enumerate(results, 1):
        size = f"{r.width}x{r.height}" if r.width and r.height else "?"
        dur = f" {r.duration_sec:.0f}s" if r.duration_sec else ""
        title = r.title[:55] + ("…" if len(r.title) > 55 else "")
        print(f"{i:>3}. [{r.provider:<7}] {r.media_type:<5} {size:>9}{dur}  {title}")


def _make_progress_printer() -> callable:
    """Tạo callback in tiến độ: in mốc trạng thái + mỗi 25% với file lớn."""
    last_pct: dict[int, int] = {}

    def on_progress(state: JobState) -> None:
        name = state.result.title[:40]
        if state.status == JobStatus.DOWNLOADING and state.bytes_total > 5 * 1024 * 1024:
            pct = int(state.bytes_done * 100 / state.bytes_total) if state.bytes_total else 0
            milestone = pct // 25 * 25
            if milestone > last_pct.get(state.index, -1):
                last_pct[state.index] = milestone
                mb_done = state.bytes_done / 1024 / 1024
                mb_total = state.bytes_total / 1024 / 1024
                print(f"  ⬇ #{state.index} {name}: {milestone}% ({mb_done:.1f}/{mb_total:.1f} MB)")
        elif state.status == JobStatus.DONE:
            print(f"  ✔ #{state.index} Xong: {state.file_path.name if state.file_path else name}")
        elif state.status == JobStatus.SKIPPED_DUPLICATE:
            print(f"  ↷ #{state.index} Trùng — bỏ qua: {name} ({state.error})")
        elif state.status == JobStatus.FAILED:
            print(f"  ✘ #{state.index} Lỗi: {name} — {state.error}")

    return on_progress


async def _cmd_search(args: argparse.Namespace) -> int:
    """Thực thi lệnh search (+ download nếu có --download)."""
    config = load_config()
    keys = ApiKeys()
    names = [n.strip().lower() for n in args.providers.split(",") if n.strip()]

    timeout = httpx.Timeout(30.0, read=120.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        providers = _build_providers(names, keys, client, config)
        if not providers:
            print("Không có provider nào khả dụng — kiểm tra .env và tham số --providers.")
            return 1

        media_types = (
            [MediaType.IMAGE, MediaType.VIDEO]
            if args.media_type == "both"
            else [MediaType(args.media_type)]
        )

        groups: list[list[SearchResult]] = []
        for media_type in media_types:
            tasks = [
                p.search(args.query, media_type, per_page=args.limit)
                for p in providers.values()
                if media_type in p.supported_types
            ]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for pname, outcome in zip(providers, outcomes, strict=False):
                if isinstance(outcome, BaseException):
                    logger.error("Search {} lỗi: {}", pname, outcome)
                    print(f"⚠ Lỗi khi tìm trên {pname}: {outcome}")
                else:
                    groups.append(outcome)

        results = _interleave(groups)[: args.limit]
        if not results:
            print("Không tìm thấy kết quả nào.")
            return 0
        _print_results(results)

        if not args.download:
            return 0

        # ---------- Download ----------
        print(f"\nBắt đầu tải {len(results)} file vào project '{args.project}'...")
        engine = get_engine(config.library_root / "mediaharvester.db")
        init_db(engine)
        manager = DownloadManager(
            config, engine, providers, args.project, progress_cb=_make_progress_printer()
        )
        for r in results:
            manager.add(r, keyword=args.query)
        await manager.run()

        counts: dict[str, int] = {}
        for st in manager.states:
            counts[st.status] = counts.get(st.status, 0) + 1
        print("\n===== Tổng kết =====")
        label = {
            JobStatus.DONE: "Tải xong",
            JobStatus.SKIPPED_DUPLICATE: "Bỏ qua (trùng)",
            JobStatus.FAILED: "Thất bại",
            JobStatus.CANCELLED: "Đã hủy",
        }
        for status, count in counts.items():
            print(f"  {label.get(status, status)}: {count}")
        quota = {k: v for k, v in manager.quota_remaining().items() if k in providers}
        print(f"  Quota còn lại (ước tính): {quota}")
        print(f"  Thư viện: {config.library_root.resolve()}")
        return 0


async def _cmd_download(args: argparse.Namespace) -> int:
    """Tải video từ URL bất kỳ qua yt-dlp (kèm cắt đoạn nếu có --clip)."""
    from mediaharvester.providers.ytdlp_provider import YtDlpProvider

    config = load_config()
    provider = YtDlpProvider(cookies_from_browser=config.ytdlp.cookies_from_browser)

    print(f"Đang lấy metadata: {args.url} ...")
    try:
        result = await provider.resolve_url(args.url, clip=args.clip)
    except ValueError as exc:  # định dạng --clip sai
        print(f"✘ {exc}")
        return 1
    except Exception as exc:
        logger.error("Không lấy được metadata {}: {}", args.url, exc)
        print(f"✘ Không lấy được metadata — kiểm tra URL: {exc}")
        return 1

    dur = f" — {result.duration_sec:.0f}s" if result.duration_sec else ""
    clip_note = f" (cắt đoạn {args.clip})" if args.clip else ""
    print(f"Video: {result.title}{dur}{clip_note}")

    keyword = urlparse(args.url).netloc.removeprefix("www.") or "direct-url"
    engine = get_engine(config.library_root / "mediaharvester.db")
    init_db(engine)
    manager = DownloadManager(
        config, engine, {"ytdlp": provider}, args.project,
        progress_cb=_make_progress_printer(),
    )
    manager.add(result, keyword=keyword)
    await manager.run()

    state = manager.states[0]
    if state.status == JobStatus.DONE:
        print(f"\n✔ Hoàn tất: {state.file_path}")
        info_json = state.file_path.with_suffix(".info.json") if state.file_path else None
        if info_json and info_json.exists():
            print(f"  Metadata: {info_json.name}")
        return 0
    print(f"\n✘ Kết thúc với trạng thái: {state.status} — {state.error or ''}")
    return 0 if state.status == JobStatus.SKIPPED_DUPLICATE else 1


def main(argv: list[str] | None = None) -> int:
    """Chạy CLI. Trả về exit code."""
    _force_utf8_console()
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {"search": _cmd_search, "download": _cmd_download}
    handler = commands.get(args.command or "")
    if handler is not None:
        try:
            return asyncio.run(handler(args))
        except KeyboardInterrupt:
            print("\nĐã dừng theo yêu cầu người dùng.")
            return 130
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
