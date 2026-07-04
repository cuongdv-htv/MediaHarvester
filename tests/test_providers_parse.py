"""Test parse JSON API → SearchResult cho Pexels và Pixabay (mock respx)."""

from __future__ import annotations

import httpx
import respx

from mediaharvester.providers.base import MediaType
from mediaharvester.providers.pexels import PexelsProvider, _pick_video_file
from mediaharvester.providers.pixabay import PixabayProvider, _pick_video_variant

PEXELS_PHOTOS = {
    "photos": [
        {
            "id": 123,
            "width": 4000,
            "height": 3000,
            "url": "https://www.pexels.com/photo/123/",
            "photographer": "Nguyen Van A",
            "alt": "Solar panels on a roof",
            "src": {
                "original": "https://images.pexels.com/photos/123/photo.jpeg",
                "medium": "https://images.pexels.com/photos/123/photo.jpeg?h=350",
            },
        }
    ]
}

PEXELS_VIDEOS = {
    "videos": [
        {
            "id": 456,
            "width": 1920,
            "height": 1080,
            "duration": 12,
            "url": "https://www.pexels.com/video/456/",
            "image": "https://images.pexels.com/videos/456/thumb.jpg",
            "user": {"name": "Tran B"},
            "video_files": [
                {"id": 1, "quality": "sd", "file_type": "video/mp4", "height": 540,
                 "link": "https://player.vimeo.com/sd.mp4"},
                {"id": 2, "quality": "hd", "file_type": "video/mp4", "height": 1080,
                 "link": "https://player.vimeo.com/hd.mp4"},
                {"id": 3, "quality": "uhd", "file_type": "video/mp4", "height": 2160,
                 "link": "https://player.vimeo.com/uhd.mp4"},
            ],
        }
    ]
}

PIXABAY_IMAGES = {
    "hits": [
        {
            "id": 789,
            "pageURL": "https://pixabay.com/photos/789/",
            "tags": "solar, panel, energy",
            "webformatURL": "https://cdn.pixabay.com/web.jpg",
            "largeImageURL": "https://cdn.pixabay.com/large.jpg",
            "imageWidth": 3840,
            "imageHeight": 2160,
            "user": "Le C",
        }
    ]
}

PIXABAY_VIDEOS = {
    "hits": [
        {
            "id": 999,
            "pageURL": "https://pixabay.com/videos/999/",
            "tags": "city, timelapse",
            "duration": 30,
            "user": "Pham D",
            "videos": {
                "large": {"url": "https://cdn.pixabay.com/l.mp4", "width": 1920,
                          "height": 1080, "thumbnail": "https://cdn.pixabay.com/l.jpg"},
                "small": {"url": "https://cdn.pixabay.com/s.mp4", "width": 960,
                          "height": 540, "thumbnail": "https://cdn.pixabay.com/s.jpg"},
            },
        }
    ]
}


@respx.mock
async def test_pexels_parse_photos() -> None:
    """Pexels photos JSON → SearchResult đầy đủ trường."""
    respx.get("https://api.pexels.com/v1/search").mock(
        return_value=httpx.Response(200, json=PEXELS_PHOTOS)
    )
    async with httpx.AsyncClient() as client:
        provider = PexelsProvider(api_key="test-key", client=client)
        results = await provider.search("solar panel", MediaType.IMAGE)
    assert len(results) == 1
    r = results[0]
    assert r.provider == "pexels"
    assert r.media_type == MediaType.IMAGE
    assert r.title == "Solar panels on a roof"
    assert r.download_url.endswith("photo.jpeg")
    assert r.author == "Nguyen Van A"
    assert r.license == "Pexels License"
    assert (r.width, r.height) == (4000, 3000)


@respx.mock
async def test_pexels_parse_videos() -> None:
    """Pexels videos JSON → SearchResult video kèm video_files trong extra."""
    respx.get("https://api.pexels.com/videos/search").mock(
        return_value=httpx.Response(200, json=PEXELS_VIDEOS)
    )
    async with httpx.AsyncClient() as client:
        provider = PexelsProvider(api_key="test-key", client=client)
        results = await provider.search("city", MediaType.VIDEO)
    r = results[0]
    assert r.media_type == MediaType.VIDEO
    assert r.duration_sec == 12.0
    assert r.download_url == "https://player.vimeo.com/hd.mp4"  # 1080 ≤ 1080p
    assert len(r.extra["video_files"]) == 3


def test_pexels_pick_video_file_quality() -> None:
    """Chọn file video đúng theo quality yêu cầu."""
    files = PEXELS_VIDEOS["videos"][0]["video_files"]
    assert _pick_video_file(files, "720p")["height"] == 540
    assert _pick_video_file(files, "1080p")["height"] == 1080
    assert _pick_video_file(files, "2160p")["height"] == 2160


@respx.mock
async def test_pixabay_parse_images() -> None:
    """Pixabay images JSON → SearchResult; key truyền qua query param."""
    route = respx.get("https://pixabay.com/api/").mock(
        return_value=httpx.Response(200, json=PIXABAY_IMAGES)
    )
    async with httpx.AsyncClient() as client:
        provider = PixabayProvider(api_key="pix-key", client=client)
        results = await provider.search("solar", MediaType.IMAGE)
    assert "key=pix-key" in str(route.calls[0].request.url)
    r = results[0]
    assert r.provider == "pixabay"
    assert r.download_url == "https://cdn.pixabay.com/large.jpg"
    assert r.license == "Pixabay Content License"
    assert r.author == "Le C"


@respx.mock
async def test_pixabay_parse_videos() -> None:
    """Pixabay videos JSON → SearchResult video chọn variant mặc định 1080p."""
    respx.get("https://pixabay.com/api/videos/").mock(
        return_value=httpx.Response(200, json=PIXABAY_VIDEOS)
    )
    async with httpx.AsyncClient() as client:
        provider = PixabayProvider(api_key="pix-key", client=client)
        results = await provider.search("city", MediaType.VIDEO)
    r = results[0]
    assert r.download_url == "https://cdn.pixabay.com/l.mp4"
    assert r.duration_sec == 30.0


def test_pixabay_pick_variant_quality() -> None:
    """Chọn variant video đúng theo quality."""
    videos = PIXABAY_VIDEOS["hits"][0]["videos"]
    assert _pick_video_variant(videos, "720p")["height"] == 540
    assert _pick_video_variant(videos, "1080p")["height"] == 1080
