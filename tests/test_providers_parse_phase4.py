"""Unit test parse JSON → SearchResult cho các provider Phase 4 (mock respx)."""

from __future__ import annotations

import httpx
import respx

from mediaharvester.providers.base import MediaType
from mediaharvester.providers.nasa import NasaProvider, pick_asset_url
from mediaharvester.providers.openverse import OpenverseProvider, _license_text
from mediaharvester.providers.unsplash import UnsplashProvider
from mediaharvester.providers.wikimedia import WikimediaProvider, _strip_html

UNSPLASH_JSON = {
    "results": [
        {
            "id": "abc",
            "width": 5000,
            "height": 3333,
            "description": None,
            "alt_description": "wind turbines on hill",
            "urls": {"full": "https://images.unsplash.com/full.jpg",
                     "small": "https://images.unsplash.com/small.jpg"},
            "links": {"html": "https://unsplash.com/photos/abc",
                      "download_location": "https://api.unsplash.com/photos/abc/download"},
            "user": {"name": "Anh A"},
        }
    ]
}

OPENVERSE_JSON = {
    "results": [
        {
            "id": "11111111-2222",
            "title": "Wind farm",
            "url": "https://upload.example.org/full.jpg",
            "thumbnail": "https://api.openverse.org/thumb.jpg",
            "foreign_landing_url": "https://flickr.com/x",
            "license": "by-sa",
            "license_version": "4.0",
            "creator": "Chị B",
            "width": 4000,
            "height": 3000,
        }
    ]
}

WIKIMEDIA_JSON = {
    "query": {
        "pages": {
            "123": {
                "title": "File:Wind turbine.jpg",
                "imageinfo": [
                    {
                        "url": "https://upload.wikimedia.org/wind.jpg",
                        "thumburl": "https://upload.wikimedia.org/thumb.jpg",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Wind.jpg",
                        "width": 3000,
                        "height": 2000,
                        "mime": "image/jpeg",
                        "extmetadata": {
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "Artist": {"value": '<a href="/wiki/User:X">Ông C</a>'},
                        },
                    }
                ],
            }
        }
    }
}

NASA_JSON = {
    "collection": {
        "items": [
            {
                "href": "https://images-api.nasa.gov/asset/PIA00123/collection.json",
                "data": [{"nasa_id": "PIA00123", "title": "Mars sunset",
                          "photographer": "NASA/JPL"}],
                "links": [{"rel": "preview", "href": "https://images-assets.nasa.gov/t.jpg"}],
            }
        ]
    }
}


@respx.mock
async def test_unsplash_parse() -> None:
    respx.get("https://api.unsplash.com/search/photos").mock(
        return_value=httpx.Response(200, json=UNSPLASH_JSON)
    )
    async with httpx.AsyncClient() as client:
        results = await UnsplashProvider("key", client).search("wind", MediaType.IMAGE)
    r = results[0]
    assert r.title == "wind turbines on hill"
    assert r.download_url.endswith("full.jpg")
    assert r.license == "Unsplash License"
    assert r.author == "Anh A"
    assert r.extra["download_location"].endswith("/download")


@respx.mock
async def test_openverse_parse() -> None:
    respx.get("https://api.openverse.org/v1/images/").mock(
        return_value=httpx.Response(200, json=OPENVERSE_JSON)
    )
    async with httpx.AsyncClient() as client:
        results = await OpenverseProvider(client=client).search("wind", MediaType.IMAGE)
    r = results[0]
    assert r.license == "CC BY-SA 4.0"
    assert r.author == "Chị B"
    assert r.download_url.endswith("full.jpg")


def test_openverse_license_text() -> None:
    assert _license_text({"license": "cc0"}) == "CC0"
    assert _license_text({"license": "by", "license_version": "2.0"}) == "CC BY 2.0"


@respx.mock
async def test_wikimedia_parse() -> None:
    respx.get("https://commons.wikimedia.org/w/api.php").mock(
        return_value=httpx.Response(200, json=WIKIMEDIA_JSON)
    )
    async with httpx.AsyncClient() as client:
        results = await WikimediaProvider(client=client).search("wind", MediaType.IMAGE)
    r = results[0]
    assert r.title == "Wind turbine.jpg"
    assert r.license == "CC BY-SA 4.0"
    assert r.author == "Ông C"  # HTML đã được strip


def test_strip_html() -> None:
    assert _strip_html('<a href="x"><b>Tác giả</b></a>') == "Tác giả"


@respx.mock
async def test_nasa_parse() -> None:
    respx.get("https://images-api.nasa.gov/search").mock(
        return_value=httpx.Response(200, json=NASA_JSON)
    )
    async with httpx.AsyncClient() as client:
        results = await NasaProvider(client=client).search("mars", MediaType.IMAGE)
    r = results[0]
    assert r.title == "Mars sunset"
    assert r.license == "Public Domain (NASA)"
    assert r.extra["manifest"].endswith("collection.json")
    assert r.source_page_url.endswith("PIA00123")


def test_nasa_pick_asset_url() -> None:
    urls = [
        "https://images-assets.nasa.gov/image/PIA/PIA~thumb.jpg",
        "https://images-assets.nasa.gov/image/PIA/PIA~orig.jpg",
        "https://images-assets.nasa.gov/image/PIA/PIA~medium.jpg",
        "https://images-assets.nasa.gov/image/PIA/collection.json",
    ]
    assert pick_asset_url(urls, MediaType.IMAGE).endswith("~orig.jpg")
    assert pick_asset_url(urls, MediaType.VIDEO) is None
    videos = ["https://x.gov/v~mobile.mp4", "https://x.gov/v~orig.mp4"]
    assert pick_asset_url(videos, MediaType.VIDEO).endswith("~orig.mp4")
