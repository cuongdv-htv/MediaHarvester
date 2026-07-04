"""DownloadManager: queue asyncio, semaphore, retry, resume, progress callback.

- Worker pool: `max_concurrent` worker (mặc định 4), tối đa `max_per_domain`
  download song song trên cùng domain (dict semaphore theo domain).
- Retry: tenacity, exponential backoff tối đa 3 lần; lỗi 429 đọc `Retry-After`.
- Resume: stream vào `*.part` + header `Range` khi tải lại; xong rename.
- Rate limit theo provider: token-bucket từ config `rate_limits` (request/giờ).
- Trạng thái job: queued → downloading → processing → done | failed |
  skipped_duplicate | cancelled. Pause/Resume/Cancel từng job và toàn queue.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

import httpx
from loguru import logger
from sqlalchemy.engine import Engine
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from mediaharvester.core.config import AppConfig
from mediaharvester.core.database import get_or_create_project, get_session
from mediaharvester.core.dedup import (
    find_phash_duplicate,
    find_sha256_duplicate,
    phash_image,
    phash_video,
    sha256_file,
)
from mediaharvester.core.models import Asset, DownloadJob
from mediaharvester.core.organizer import build_asset_dir, write_sidecar
from mediaharvester.core.thumbnails import make_thumbnail
from mediaharvester.providers.base import MediaType, Provider, SearchResult

_CHUNK = 64 * 1024

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class JobStatus(StrEnum):
    """Trạng thái vòng đời của một download job."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    CANCELLED = "cancelled"


@dataclass
class JobState:
    """Trạng thái runtime của 1 job (GUI/CLI đọc để hiển thị progress)."""

    index: int
    result: SearchResult
    keyword: str
    project: str = "default"
    db_job_id: int | None = None
    status: JobStatus = JobStatus.QUEUED
    bytes_done: int = 0
    bytes_total: int = 0
    error: str | None = None
    file_path: Path | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


ProgressCallback = Callable[[JobState], None]


def _is_retryable(exc: BaseException) -> bool:
    """Lỗi mạng tạm thời hoặc HTTP 429/5xx thì retry."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


class _RetryAfterWait(wait_exponential):
    """Wait strategy: HTTP 429 → chờ đúng `Retry-After`; còn lại exponential backoff."""

    def __call__(self, retry_state) -> float:  # type: ignore[override]
        outcome = retry_state.outcome
        if outcome is not None:
            exc = outcome.exception()
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                retry_after = exc.response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        return max(0.0, float(retry_after))
                    except ValueError:
                        pass
        return super().__call__(retry_state)


async def download_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> Path:
    """Một lần thử tải: stream vào `{dest}.part`, resume bằng Range, xong rename.

    Caller chịu trách nhiệm retry (dùng `download_with_retry`).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}

    async with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
        if resp.status_code == 200 and offset > 0:
            # Server không hỗ trợ Range → tải lại từ đầu
            logger.debug("Server không hỗ trợ resume, tải lại từ đầu: {}", url)
            offset = 0
        resp.raise_for_status()

        content_length = int(resp.headers.get("Content-Length", 0))
        total = content_length + (offset if resp.status_code == 206 else 0)
        done = offset

        mode = "ab" if (resp.status_code == 206 and offset > 0) else "wb"
        with part.open(mode) as f:
            async for chunk in resp.aiter_bytes(_CHUNK):
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError("Job bị hủy bởi người dùng")
                f.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    progress_cb(done, total)

    part.replace(dest)
    return dest


async def download_with_retry(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_event: asyncio.Event | None = None,
    max_attempts: int = 3,
    wait_multiplier: float = 1.0,
) -> Path:
    """Tải file với retry (tenacity): tối đa `max_attempts` lần, backoff mũ, honor 429."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=_RetryAfterWait(multiplier=wait_multiplier, max=30),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    ):
        with attempt:
            if attempt.retry_state.attempt_number > 1:
                logger.info(
                    "Thử lại lần {}/{}: {}", attempt.retry_state.attempt_number, max_attempts, url
                )
            return await download_file(client, url, dest, progress_cb, cancel_event)
    raise RuntimeError("unreachable")  # pragma: no cover


class RateLimiter:
    """Token bucket đơn giản: `per_hour` request/giờ cho mỗi provider."""

    def __init__(self, per_hour: int) -> None:
        self.capacity = max(1, per_hour)
        self.tokens = float(self.capacity)
        self.rate = self.capacity / 3600.0
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(float(self.capacity), self.tokens + (now - self._updated) * self.rate)
        self._updated = now

    async def acquire(self) -> None:
        """Chờ đến khi còn quota rồi tiêu 1 token."""
        async with self._lock:
            self._refill()
            if self.tokens < 1.0:
                wait_sec = (1.0 - self.tokens) / self.rate
                logger.warning("Hết quota rate-limit, chờ {:.0f}s...", wait_sec)
                await asyncio.sleep(wait_sec)
                self._refill()
            self.tokens -= 1.0

    @property
    def remaining(self) -> int:
        """Số request còn lại trong quota hiện tại (hiển thị lên GUI/CLI)."""
        self._refill()
        return int(self.tokens)


class DownloadManager:
    """Quản lý queue download: worker pool, rate limit, dedup, ghi DB, progress."""

    def __init__(
        self,
        config: AppConfig,
        engine: Engine,
        providers: dict[str, Provider],
        project_name: str,
        progress_cb: ProgressCallback | None = None,
    ) -> None:
        self.config = config
        self.engine = engine
        self.providers = providers
        self.project_name = project_name
        self.progress_cb = progress_cb

        self._queue: asyncio.Queue[JobState] = asyncio.Queue()
        self._domain_sems: dict[str, asyncio.Semaphore] = {}
        self._workers: list[asyncio.Task] = []
        self._pause = asyncio.Event()
        self._pause.set()  # set = đang chạy
        self.rate_limiters: dict[str, RateLimiter] = {
            name: RateLimiter(limit) for name, limit in config.rate_limits.items()
        }
        self.states: list[JobState] = []
        self._project_ids: dict[str, int] = {}
        self._project_id = self._ensure_project(project_name)

    # ---------- API điều khiển ----------

    def _ensure_project(self, name: str) -> int:
        """Lấy (hoặc tạo) project id theo tên, có cache."""
        if name not in self._project_ids:
            with get_session(self.engine) as session:
                project_id = get_or_create_project(session, name).id
            assert project_id is not None
            self._project_ids[name] = project_id
        return self._project_ids[name]

    def add(self, result: SearchResult, keyword: str, project: str | None = None) -> JobState:
        """Thêm 1 kết quả tìm kiếm vào queue, tạo record DownloadJob (queued)."""
        project = project or self.project_name
        self._ensure_project(project)
        with get_session(self.engine) as session:
            db_job = DownloadJob(url=result.download_url, status=JobStatus.QUEUED)
            session.add(db_job)
            session.commit()
            session.refresh(db_job)
        state = JobState(
            index=len(self.states) + 1,
            result=result,
            keyword=keyword,
            project=project,
            db_job_id=db_job.id,
        )
        self.states.append(state)
        self._queue.put_nowait(state)
        return state

    def pause_all(self) -> None:
        """Tạm dừng toàn queue (job đang chạy dừng ở chunk kế tiếp)."""
        self._pause.clear()

    def resume_all(self) -> None:
        """Tiếp tục toàn queue."""
        self._pause.set()

    def cancel_all(self) -> None:
        """Hủy tất cả job chưa xong."""
        for state in self.states:
            state.cancel_event.set()
        self._pause.set()

    def quota_remaining(self) -> dict[str, int]:
        """Quota còn lại theo provider (hiển thị lên GUI/CLI)."""
        return {name: rl.remaining for name, rl in self.rate_limiters.items()}

    def start(self) -> None:
        """Khởi động worker pool sống lâu dài (chế độ GUI) — cần event loop đang chạy."""
        if self._workers:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("DownloadManager.start() gọi khi chưa có event loop — bỏ qua.")
            return
        n_workers = max(1, self.config.download.max_concurrent)
        self._workers = [asyncio.create_task(self._worker()) for _ in range(n_workers)]
        logger.info("DownloadManager: {} worker đã khởi động.", n_workers)

    async def stop(self) -> None:
        """Dừng worker pool (chế độ GUI, gọi khi thoát app)."""
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def run(self) -> None:
        """Chạy queue đến khi hết job rồi dừng (chế độ CLI)."""
        self.start()
        await self._queue.join()
        await self.stop()

    # ---------- Nội bộ ----------

    def _notify(self, state: JobState) -> None:
        if self.progress_cb is not None:
            self.progress_cb(state)

    def _domain_sem(self, url: str) -> asyncio.Semaphore:
        domain = urlparse(url).netloc
        if domain not in self._domain_sems:
            self._domain_sems[domain] = asyncio.Semaphore(
                max(1, self.config.download.max_per_domain)
            )
        return self._domain_sems[domain]

    def _update_db_job(self, state: JobState, asset_id: int | None = None) -> None:
        with get_session(self.engine) as session:
            db_job = session.get(DownloadJob, state.db_job_id)
            if db_job is None:
                return
            db_job.status = state.status
            db_job.error_msg = state.error
            if asset_id is not None:
                db_job.asset_id = asset_id
            if state.status in (
                JobStatus.DONE,
                JobStatus.FAILED,
                JobStatus.SKIPPED_DUPLICATE,
                JobStatus.CANCELLED,
            ):
                db_job.finished_at = datetime.now(UTC)
            session.add(db_job)
            session.commit()

    async def _worker(self) -> None:
        while True:
            state = await self._queue.get()
            try:
                await self._process(state)
            except asyncio.CancelledError:
                if state.cancel_event.is_set():
                    # Job bị user hủy giữa chừng — worker vẫn sống, xử lý job kế
                    # (finally bên dưới sẽ gọi task_done)
                    state.status = JobStatus.CANCELLED
                    self._update_db_job(state)
                    self._notify(state)
                    continue
                # Worker bị shutdown (stop/run kết thúc)
                if state.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING):
                    state.status = JobStatus.CANCELLED
                    self._update_db_job(state)
                    self._notify(state)
                raise
            except Exception as exc:
                logger.exception("Job #{} thất bại: {}", state.index, exc)
                state.status = JobStatus.FAILED
                state.error = f"{type(exc).__name__}: {exc}"
                self._update_db_job(state)
                self._notify(state)
            finally:
                self._queue.task_done()

    async def _process(self, state: JobState) -> None:
        await self._pause.wait()
        if state.cancel_event.is_set():
            state.status = JobStatus.CANCELLED
            self._update_db_job(state)
            self._notify(state)
            return

        result = state.result
        provider = self.providers[result.provider]

        limiter = self.rate_limiters.get(result.provider)
        if limiter is not None:
            await limiter.acquire()

        dest_dir = build_asset_dir(
            self.config.library_root, state.project, result.media_type, state.keyword
        )

        state.status = JobStatus.DOWNLOADING
        self._notify(state)

        def on_bytes(done: int, total: int) -> None:
            if state.cancel_event.is_set():
                # Hủy giữa chừng: raise xuyên qua provider.download (cả httpx lẫn yt-dlp)
                raise asyncio.CancelledError("Job bị hủy bởi người dùng")
            state.bytes_done = done
            state.bytes_total = total
            self._notify(state)

        async with self._domain_sem(result.download_url):
            file_path = await provider.download(
                result, dest_dir, on_bytes, self.config.default_quality
            )
        state.file_path = file_path

        # ---------- Processing: dedup + thumbnail + DB ----------
        state.status = JobStatus.PROCESSING
        self._notify(state)

        sha256 = await asyncio.to_thread(sha256_file, file_path)

        with get_session(self.engine) as session:
            dup = find_sha256_duplicate(session, sha256)
        if dup is not None:
            logger.info("Trùng sha256 với asset #{} — bỏ qua: {}", dup.id, file_path.name)
            # Chỉ xóa nếu là file MỚI ở đường dẫn khác — tên file deterministic theo URL
            # nên chạy lại cùng URL sẽ ghi đè lên chính file gốc, tuyệt đối không xóa nó.
            if Path(dup.file_path).resolve() != file_path.resolve():
                file_path.unlink(missing_ok=True)
            state.status = JobStatus.SKIPPED_DUPLICATE
            state.error = f"Trùng tuyệt đối với asset #{dup.id}"
            self._update_db_job(state)
            self._notify(state)
            return

        if result.media_type == MediaType.IMAGE:
            phash = await asyncio.to_thread(phash_image, file_path)
        else:
            phash = await asyncio.to_thread(phash_video, file_path)

        project_id = self._ensure_project(state.project)
        if phash is not None:
            with get_session(self.engine) as session:
                near = find_phash_duplicate(
                    session, project_id, phash, self.config.dedup.phash_threshold
                )
            if near is not None:
                if self.config.dedup.auto_skip_duplicates:
                    logger.info(
                        "Gần trùng (pHash) với asset #{} — auto-skip: {}", near.id, file_path.name
                    )
                    file_path.unlink(missing_ok=True)
                    state.status = JobStatus.SKIPPED_DUPLICATE
                    state.error = f"Gần trùng (pHash) với asset #{near.id}"
                    self._update_db_job(state)
                    self._notify(state)
                    return
                logger.warning(
                    "Ảnh gần trùng (pHash) với asset #{} nhưng vẫn giữ "
                    "(auto_skip_duplicates=false): {}",
                    near.id,
                    file_path.name,
                )

        thumb_dir = self.config.library_root / ".thumbnails"
        await asyncio.to_thread(make_thumbnail, file_path, result.media_type, thumb_dir)

        asset = Asset(
            project_id=project_id,
            file_path=str(file_path),
            media_type=result.media_type,
            provider=result.provider,
            source_url=result.download_url,
            source_page_url=result.source_page_url,
            license=result.license,
            author=result.author,
            title=result.title,
            keywords=state.keyword,
            width=result.width,
            height=result.height,
            duration_sec=result.duration_sec,
            filesize=file_path.stat().st_size,
            sha256=sha256,
            phash=phash,
        )
        with get_session(self.engine) as session:
            session.add(asset)
            session.commit()
            session.refresh(asset)

        write_sidecar(
            file_path,
            {
                **dataclasses.asdict(result),
                "sha256": sha256,
                "phash": phash,
                "filesize": asset.filesize,
                "keyword": state.keyword,
                "project": state.project,
                "downloaded_at": datetime.now(UTC).isoformat(),
            },
        )

        state.status = JobStatus.DONE
        self._update_db_job(state, asset_id=asset.id)
        self._notify(state)
