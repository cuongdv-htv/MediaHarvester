"""Test HeuristicKeywordExtractor: tách từ khóa Việt + Anh."""

from __future__ import annotations

from mediaharvester.utils.keywords import HeuristicKeywordExtractor

SCRIPT_VI = """
Điện mặt trời đang phát triển rất nhanh tại Việt Nam. Các trang trại
điện mặt trời quy mô lớn xuất hiện ở Ninh Thuận và Bình Thuận.
Cùng với điện mặt trời, điện gió ngoài khơi cũng được đầu tư mạnh.
Tua bin gió khổng lồ mọc lên dọc bờ biển. Chi phí sản xuất điện gió
giảm liên tục trong mười năm qua khiến điện gió trở nên cạnh tranh.
"""

SCRIPT_EN = """
Solar panels are becoming cheaper every year. Large solar farms
now produce electricity at record low prices. Wind turbines,
especially offshore wind turbines, complement solar panels well.
The energy transition depends on solar panels and wind turbines.
"""


def test_extract_vietnamese() -> None:
    keywords = HeuristicKeywordExtractor().extract(SCRIPT_VI)
    assert keywords, "Phải tách được từ khóa"
    joined = " | ".join(keywords)
    # Các cụm chủ đề chính phải xuất hiện
    assert "điện mặt trời" in joined
    assert "điện gió" in joined
    # Stopword thuần túy không được thành keyword
    assert "đang" not in keywords
    assert "cũng" not in keywords


def test_extract_english() -> None:
    keywords = HeuristicKeywordExtractor().extract(SCRIPT_EN)
    joined = " | ".join(keywords)
    assert "solar panels" in joined
    assert "wind turbines" in joined
    assert "the" not in keywords


def test_phrases_deduped() -> None:
    """Cụm con của cụm đã chọn không được lặp lại."""
    keywords = HeuristicKeywordExtractor().extract(SCRIPT_EN)
    for i, kw in enumerate(keywords):
        for other in keywords[i + 1 :]:
            assert kw not in other and other not in kw


def test_max_keywords_limit() -> None:
    keywords = HeuristicKeywordExtractor().extract(SCRIPT_VI + SCRIPT_EN, max_keywords=5)
    assert len(keywords) <= 5


def test_empty_text() -> None:
    assert HeuristicKeywordExtractor().extract("") == []
    assert HeuristicKeywordExtractor().extract("và của là những") == []
