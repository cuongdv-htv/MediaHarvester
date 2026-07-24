"""Base cho provider dùng API key có xoay vòng (pexels/pixabay/unsplash).

`KeyedProvider._request(make)` gọi API bằng key hiện tại; nếu gặp giới hạn
(429 / quota=0 / 403 quota) thì cho key nghỉ và tự thử lại bằng key kế tiếp,
đến khi thành công hoặc hết key khả dụng.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from loguru import logger

from mediaharvester.core.keypool import ApiKeyPool, split_keys
from mediaharvester.providers.base import Provider


def _retry_after(resp: httpx.Response) -> float | None:
    """Số giây cần chờ từ header `Retry-After` (nếu có)."""
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return None


def _remaining_zero(resp: httpx.Response) -> bool:
    """True nếu header quota còn lại về 0 (Pexels/Pixabay/Unsplash đều dùng tên này)."""
    raw = resp.headers.get("X-Ratelimit-Remaining")
    if raw is None:
        return False
    try:
        return int(raw) <= 0
    except ValueError:
        return False


class KeyedProvider(Provider):
    """Provider có pool key xoay vòng. Giữ tương thích `cls(api_key=..., client=...)`."""

    requires_api_key = True

    def __init__(
        self,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
        *,
        api_keys: list[str] | None = None,
        cooldown_sec: int = 0,
        state_path: Path | str | None = None,
    ) -> None:
        keys = list(api_keys) if api_keys else split_keys(api_key)
        self.keys = ApiKeyPool(
            self.name, keys, cooldown_sec=cooldown_sec, state_path=state_path
        )
        self._client = client or httpx.AsyncClient(timeout=30)

    @property
    def api_key(self) -> str:
        """Key sẵn sàng hiện tại (rỗng nếu pool cạn) — cho code cũ tham chiếu."""
        return self.keys.current() or ""

    async def _request(
        self, make: Callable[[str], Awaitable[httpx.Response]]
    ) -> httpx.Response:
        """Gọi `make(key)` có xoay key khi chạm giới hạn.

        - 429 hoặc 403 → key nghỉ, thử key kế tiếp. Unsplash báo **hết rate-limit
          bằng 403** (không phải 401) nên 403 luôn được coi là chạm giới hạn —
          nếu loại hẳn key ở đây thì chỉ vài lượt là sạch pool và hết đường xoay.
        - 401 → key sai thật, loại khỏi vòng rồi thử key kế tiếp.
        - Thành công mà quota về 0 → chủ động cho key nghỉ (lần sau xoay ngay).
        Hết key khả dụng → raise RuntimeError để caller báo lỗi thân thiện.
        """
        n = max(1, len(self.keys))
        for _ in range(n):
            key = self.keys.current()
            if key is None:
                break
            resp = await make(key)
            status = resp.status_code
            if status in (429, 403):
                self.keys.mark_exhausted(key, _retry_after(resp))
                continue
            if status == 401:
                self.keys.mark_invalid(key)
                continue
            if resp.is_success and _remaining_zero(resp):
                self.keys.mark_exhausted(key, _retry_after(resp))
            return resp
        raise RuntimeError(
            f"{self.name}: tất cả {len(self.keys)} API key đều đã hết hạn mức "
            "hoặc không hợp lệ — thử lại sau hoặc bổ sung key trong Cài đặt."
        )

    async def health_check(self) -> bool:
        """Mặc định: pool còn ≥1 key sẵn sàng thì coi như có thể thử."""
        if self.keys.current() is None:
            logger.warning("[{}] không còn key sẵn sàng.", self.name)
            return False
        return True
