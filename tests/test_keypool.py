"""Test xoay vòng API key: ApiKeyPool + KeyedProvider (mock respx)."""

from __future__ import annotations

import httpx
import respx

from mediaharvester.core.keypool import ApiKeyPool, mask_key, split_keys
from mediaharvester.providers.base import MediaType
from mediaharvester.providers.pexels import PexelsProvider


class _Clock:
    """Đồng hồ giả điều khiển được cho test cooldown."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_split_keys() -> None:
    """Tách key theo dấu phẩy / xuống dòng / khoảng trắng, bỏ rỗng."""
    assert split_keys("a,b , c\nd\n\ne;f") == ["a", "b", "c", "d", "e", "f"]
    assert split_keys("   ") == []


def test_mask_key_khong_lo_key_that() -> None:
    """Id ẩn danh không chứa toàn bộ key thật."""
    masked = mask_key("supersecretkey1234")
    assert "supersecret" not in masked
    assert "1234" in masked  # chỉ lộ đuôi key


def test_pool_bo_trung_giu_thu_tu() -> None:
    """Pool bỏ key trùng nhưng giữ thứ tự người dùng nhập."""
    pool = ApiKeyPool("x", ["k1", "k2", "k1", "k3"])
    assert len(pool) == 3
    assert pool.current() == "k1"


def test_rotate_khi_het_han_muc() -> None:
    """Key chạm giới hạn → nghỉ và xoay sang key kế tiếp."""
    clock = _Clock()
    pool = ApiKeyPool("x", ["k1", "k2", "k3"], cooldown_sec=100, clock=clock)
    assert pool.current() == "k1"
    pool.mark_exhausted("k1")
    assert pool.current() == "k2"
    pool.mark_exhausted("k2")
    assert pool.current() == "k3"


def test_cooldown_het_han_thi_key_dung_lai() -> None:
    """Hết thời gian nghỉ, key sẵn sàng trở lại."""
    clock = _Clock()
    pool = ApiKeyPool("x", ["k1", "k2"], cooldown_sec=100, clock=clock)
    pool.mark_exhausted("k1")
    assert pool.current() == "k2"
    pool.mark_exhausted("k2")
    assert pool.current() is None  # cả hai đang nghỉ
    clock.t += 101  # qua thời gian cooldown
    assert pool.current() in ("k1", "k2")
    assert pool.stats()["ready"] == 2


def test_retry_after_uu_tien() -> None:
    """`Retry-After` được ưu tiên hơn cooldown_sec mặc định."""
    clock = _Clock()
    pool = ApiKeyPool("x", ["k1", "k2"], cooldown_sec=10, clock=clock)
    pool.mark_exhausted("k1", retry_after=500)
    clock.t += 20  # qua cooldown_sec nhưng chưa qua retry_after
    assert pool.current() == "k2"  # k1 vẫn đang nghỉ theo retry_after


def test_mark_invalid_loai_han() -> None:
    """Key sai bị loại khỏi vòng, không quay lại kể cả sau cooldown."""
    clock = _Clock()
    pool = ApiKeyPool("x", ["k1", "k2"], cooldown_sec=1, clock=clock)
    pool.mark_invalid("k1")
    clock.t += 999
    assert pool.current() == "k2"
    assert pool.stats() == {"total": 2, "ready": 1, "cooling": 0, "invalid": 1}


def test_persist_giu_cooldown_qua_khoi_dong(tmp_path) -> None:
    """Trạng thái nghỉ lưu ra file và khôi phục ở pool mới (cùng ngày)."""
    state = tmp_path / ".keystate.json"
    clock = _Clock()
    pool = ApiKeyPool("pexels", ["k1", "k2"], cooldown_sec=1000, state_path=state, clock=clock)
    pool.mark_exhausted("k1")
    assert state.exists()
    # Pool mới đọc lại state: k1 vẫn đang nghỉ
    pool2 = ApiKeyPool("pexels", ["k1", "k2"], state_path=state, clock=clock)
    assert pool2.current() == "k2"


def test_persist_khong_luu_key_that(tmp_path) -> None:
    """File state không được chứa key thật (chỉ id ẩn danh)."""
    state = tmp_path / ".keystate.json"
    pool = ApiKeyPool("pexels", ["supersecretkey"], cooldown_sec=1000, state_path=state)
    pool.mark_exhausted("supersecretkey")
    assert "supersecretkey" not in state.read_text(encoding="utf-8")


@respx.mock
async def test_pexels_xoay_key_khi_429() -> None:
    """Pexels: key1 bị 429 → tự đổi key2 và trả kết quả thành công."""
    route = respx.get("https://api.pexels.com/v1/search").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3600"}),
            httpx.Response(200, json={"photos": []}),
        ]
    )
    async with httpx.AsyncClient() as client:
        provider = PexelsProvider(api_keys=["key1", "key2"], client=client)
        results = await provider.search("solar", MediaType.IMAGE)
    assert results == []
    assert route.call_count == 2
    # key1 đã bị đánh dấu nghỉ, chỉ còn key2 sẵn sàng
    assert provider.keys.stats() == {"total": 2, "ready": 1, "cooling": 1, "invalid": 0}


@respx.mock
async def test_pexels_het_key_thi_raise() -> None:
    """Mọi key đều 429 → RuntimeError để báo lỗi thân thiện."""
    respx.get("https://api.pexels.com/v1/search").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "3600"})
    )
    async with httpx.AsyncClient() as client:
        provider = PexelsProvider(api_keys=["k1", "k2"], client=client)
        try:
            await provider.search("solar", MediaType.IMAGE)
        except RuntimeError as exc:
            assert "API key" in str(exc)
        else:
            raise AssertionError("Phải raise RuntimeError khi hết key")
