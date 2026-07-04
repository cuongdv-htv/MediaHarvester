"""Test cho ytdlp_provider: parse clip, map entries, build ydl opts."""

from __future__ import annotations

from pathlib import Path

import pytest

from mediaharvester.providers.base import MediaType
from mediaharvester.providers.ytdlp_provider import (
    YtDlpProvider,
    _entries_to_results,
    parse_clip_range,
)


class TestParseClipRange:
    """parse_clip_range: hh:mm:ss-hh:mm:ss → (start_sec, end_sec)."""

    def test_full_format(self) -> None:
        assert parse_clip_range("00:01:00-00:01:30") == (60.0, 90.0)

    def test_mm_ss(self) -> None:
        assert parse_clip_range("01:00-01:30") == (60.0, 90.0)

    def test_seconds_only(self) -> None:
        assert parse_clip_range("5-35") == (5.0, 35.0)

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="không hợp lệ"):
            parse_clip_range("abc")

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError, match="phải sau"):
            parse_clip_range("00:01:30-00:01:00")


def test_entries_to_results_mapping() -> None:
    """Entry flat từ ytsearch → SearchResult đầy đủ trường."""
    entries = [
        {
            "id": "abc123",
            "title": "Solar Farm Aerial 4K",
            "url": "https://www.youtube.com/watch?v=abc123",
            "duration": 95,
            "uploader": "Kênh Test",
            "thumbnails": [
                {"url": "https://i.ytimg.com/vi/abc123/default.jpg"},
                {"url": "https://i.ytimg.com/vi/abc123/hqdefault.jpg"},
            ],
        },
        None,  # entry hỏng phải được bỏ qua
    ]
    results = _entries_to_results(entries)
    assert len(results) == 1
    r = results[0]
    assert r.provider == "ytdlp"
    assert r.media_type == MediaType.VIDEO
    assert r.title == "Solar Farm Aerial 4K"
    assert r.duration_sec == 95.0
    assert r.author == "Kênh Test"
    assert r.thumbnail_url.endswith("hqdefault.jpg")  # lấy thumbnail lớn nhất (cuối list)
    assert r.download_url == "https://www.youtube.com/watch?v=abc123"


def test_entries_without_url_fallback_to_id() -> None:
    """Entry thiếu url → dựng từ video id."""
    results = _entries_to_results([{"id": "xyz789", "title": "t"}])
    assert results[0].download_url == "https://www.youtube.com/watch?v=xyz789"


class TestBuildYdlOpts:
    """build_ydl_opts: format, infojson, cắt đoạn."""

    def test_format_respects_quality(self, tmp_path: Path) -> None:
        provider = YtDlpProvider()
        opts = provider.build_ydl_opts(tmp_path / "base", "720p", clip=None)
        assert "height<=720" in opts["format"]
        assert opts["merge_output_format"] == "mp4"
        assert opts["writeinfojson"] is True
        assert opts["format_sort"] == ["vcodec:h264"]
        assert "download_ranges" not in opts

    def test_clip_adds_download_ranges(self, tmp_path: Path) -> None:
        provider = YtDlpProvider()
        opts = provider.build_ydl_opts(tmp_path / "base", "1080p", clip="00:00:05-00:00:35")
        assert "download_ranges" in opts
        assert opts["force_keyframes_at_cuts"] is True

    def test_cookies_from_browser(self, tmp_path: Path) -> None:
        provider = YtDlpProvider(cookies_from_browser="edge")
        opts = provider.build_ydl_opts(tmp_path / "base", "1080p", clip=None)
        assert opts["cookiesfrombrowser"] == ("edge",)

    def test_outtmpl_uses_dest_base(self, tmp_path: Path) -> None:
        provider = YtDlpProvider()
        opts = provider.build_ydl_opts(tmp_path / "ytdlp_video_ab12cd34", "1080p", clip=None)
        assert opts["outtmpl"].endswith("ytdlp_video_ab12cd34.%(ext)s")


async def test_health_check() -> None:
    """yt-dlp đã cài → health check True."""
    assert await YtDlpProvider().health_check() is True
