"""Xoay vòng nhiều API key khi chạm giới hạn free trong ngày.

Ý tưởng: mỗi provider có 1 pool nhiều key. Khi key hiện tại chạm giới hạn
(HTTP 429 / quota về 0), pool cho key đó "nghỉ" (cooldown) và xoay sang key kế
tiếp. Key sai (401/403 auth) bị loại khỏi vòng trong phiên chạy.

Trạng thái cooldown có thể lưu ra JSON để giữ qua các lần khởi động **trong ngày**
— file chỉ chứa *id ẩn danh* của key (đuôi + độ dài), KHÔNG BAO GIỜ lưu key thật
(đúng ràng buộc: key chỉ tồn tại trong .env).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

_SPLIT_RE = re.compile(r"[,\s;]+")


def split_keys(raw: str) -> list[str]:
    """Tách chuỗi nhiều key (phân cách bởi dấu phẩy / xuống dòng / khoảng trắng)."""
    return [k for k in _SPLIT_RE.split(raw.strip()) if k]


def mask_key(key: str) -> str:
    """Id ẩn danh của key để log/persist mà không lộ key thật."""
    k = key.strip()
    if len(k) <= 4:
        return f"…{k[-2:]}"
    return f"…{k[-4:]}·{len(k)}"


def _end_of_day_epoch(now: float) -> float:
    """Mốc thời gian nửa đêm kế tiếp (giờ địa phương) — dùng cho giới hạn 'theo ngày'."""
    dt = datetime.fromtimestamp(now).astimezone()
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight + timedelta(days=1)).timestamp()


@dataclass
class _Entry:
    """Một key trong pool cùng trạng thái nghỉ/loại."""

    key: str
    cooldown_until: float = 0.0  # epoch; ≤ now nghĩa là sẵn sàng
    invalid: bool = False  # key sai → loại hẳn trong phiên


class ApiKeyPool:
    """Pool key có xoay vòng khi chạm giới hạn.

    - `cooldown_sec=0` → key chạm giới hạn nghỉ tới hết ngày (nửa đêm kế tiếp);
      >0 → nghỉ đúng số giây đó. `Retry-After` từ server luôn được ưu tiên.
    - `state_path` (tùy chọn) → lưu/khôi phục cooldown giữa các lần chạy.
    """

    def __init__(
        self,
        provider: str,
        keys: list[str],
        *,
        cooldown_sec: int = 0,
        state_path: Path | str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.provider = provider
        self.cooldown_sec = cooldown_sec
        self._clock = clock
        # Bỏ trùng, giữ thứ tự người dùng nhập
        seen: set[str] = set()
        self._entries: list[_Entry] = []
        for raw in keys:
            k = raw.strip()
            if k and k not in seen:
                seen.add(k)
                self._entries.append(_Entry(k))
        self._idx = 0
        self._state_path = Path(state_path) if state_path else None
        self._load_state()

    def __len__(self) -> int:
        return len(self._entries)

    # ---------- Truy vấn ----------

    def _available(self, e: _Entry) -> bool:
        return not e.invalid and e.cooldown_until <= self._clock()

    def current(self) -> str | None:
        """Key sẵn sàng hiện tại; None nếu mọi key đang nghỉ/không hợp lệ."""
        n = len(self._entries)
        if n == 0:
            return None
        for off in range(n):
            idx = (self._idx + off) % n
            if self._available(self._entries[idx]):
                self._idx = idx
                return self._entries[idx].key
        return None

    def stats(self) -> dict[str, int]:
        """Thống kê để hiển thị GUI: tổng / sẵn sàng / đang nghỉ / lỗi."""
        now = self._clock()
        cooling = sum(
            1 for e in self._entries if not e.invalid and e.cooldown_until > now
        )
        invalid = sum(1 for e in self._entries if e.invalid)
        return {
            "total": len(self._entries),
            "ready": len(self._entries) - cooling - invalid,
            "cooling": cooling,
            "invalid": invalid,
        }

    # ---------- Cập nhật trạng thái ----------

    def _find(self, key: str) -> _Entry | None:
        return next((e for e in self._entries if e.key == key), None)

    def _advance_from(self, key: str) -> None:
        """Nếu `key` đang là con trỏ hiện tại thì nhích sang key kế tiếp."""
        if self._entries and self._entries[self._idx].key == key:
            self._idx = (self._idx + 1) % len(self._entries)

    def _cooldown_target(self, retry_after: float | None) -> float:
        now = self._clock()
        if retry_after is not None and retry_after > 0:
            return now + retry_after
        if self.cooldown_sec > 0:
            return now + self.cooldown_sec
        return _end_of_day_epoch(now)

    def mark_exhausted(self, key: str, retry_after: float | None = None) -> None:
        """Đánh dấu key chạm giới hạn → nghỉ rồi xoay sang key kế tiếp."""
        e = self._find(key)
        if e is None:
            return
        e.cooldown_until = self._cooldown_target(retry_after)
        until = datetime.fromtimestamp(e.cooldown_until).strftime("%H:%M %d/%m")
        logger.warning(
            "[{}] key {} chạm giới hạn — nghỉ tới {} (còn {} key sẵn sàng).",
            self.provider, mask_key(key), until, self.stats()["ready"],
        )
        self._advance_from(key)
        self._save_state()

    def mark_invalid(self, key: str) -> None:
        """Đánh dấu key sai (401/403 auth) → loại khỏi vòng xoay trong phiên."""
        e = self._find(key)
        if e is None:
            return
        e.invalid = True
        logger.error(
            "[{}] key {} không hợp lệ — loại khỏi vòng xoay.", self.provider, mask_key(key)
        )
        self._advance_from(key)

    # ---------- Lưu/khôi phục cooldown (id ẩn danh) ----------

    def _load_state(self) -> None:
        if not self._state_path or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Không đọc được key-state ({}) — bỏ qua.", exc)
            return
        prov = data.get(self.provider, {})
        now = self._clock()
        for e in self._entries:
            until = prov.get(mask_key(e.key))
            if isinstance(until, (int, float)) and until > now:
                e.cooldown_until = float(until)

    def _save_state(self) -> None:
        if not self._state_path:
            return
        data: dict = {}
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        now = self._clock()
        data[self.provider] = {
            mask_key(e.key): e.cooldown_until
            for e in self._entries
            if not e.invalid and e.cooldown_until > now
        }
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Không lưu được key-state: {}", exc)
