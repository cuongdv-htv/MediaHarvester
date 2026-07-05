"""Kịch bản → từ khóa: tách keywords từ văn bản bằng heuristic.

Interface `KeywordExtractor` được chừa sẵn để sau này thay bằng LLM API
(chỉ cần implement class mới, GUI không đổi).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import Counter

# Stopwords tiếng Việt (không dấu hóa KHÔNG áp dụng — giữ nguyên có dấu)
_STOPWORDS_VI = {
    "và", "là", "của", "có", "được", "cho", "không", "với", "này", "đó", "các",
    "những", "một", "để", "khi", "thì", "mà", "ở", "ra", "vào", "cũng", "như",
    "đã", "sẽ", "đang", "bị", "về", "trên", "dưới", "trong", "ngoài", "tại",
    "từ", "đến", "theo", "nếu", "vì", "nên", "do", "bởi", "hay", "hoặc",
    "nhưng", "còn", "rằng", "nhiều", "rất", "chỉ", "lại", "nữa", "thêm",
    "phải", "ai", "gì", "sao", "đâu", "nào", "bao", "giờ", "người", "việc",
    "cách", "điều", "sự", "cái", "con", "chiếc", "vậy", "đây", "kia", "ấy",
    "nó", "họ", "ta", "tôi", "bạn", "chúng", "mình", "hơn", "quá", "lên",
    "xuống", "qua", "sau", "trước", "giữa", "bên", "cùng", "đều", "vẫn",
    "chưa", "từng", "mỗi", "mọi", "cả", "thế", "làm", "năm", "tháng", "ngày",
}

_STOPWORDS_EN = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "for", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "can", "could", "should", "may", "might", "must", "this",
    "that", "these", "those", "it", "its", "they", "them", "their", "we",
    "our", "you", "your", "he", "she", "his", "her", "i", "my", "me", "not",
    "no", "so", "than", "then", "there", "here", "what", "which", "who",
    "when", "where", "why", "how", "all", "any", "both", "each", "more",
    "most", "other", "some", "such", "only", "own", "same", "too", "very",
    "just", "also", "into", "over", "under", "about", "between", "through",
    "during", "before", "after", "again", "once", "up", "down", "out", "off",
}

_STOPWORDS = _STOPWORDS_VI | _STOPWORDS_EN
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"[.!?;:\n\r]+")


class KeywordExtractor(ABC):
    """Interface tách từ khóa — sau này có thể thay bằng LLM API."""

    @abstractmethod
    def extract(self, text: str, max_keywords: int = 12) -> list[str]:
        """Trả về danh sách từ khóa (mỗi keyword là cụm 1–3 từ)."""


class HeuristicKeywordExtractor(KeywordExtractor):
    """Tách keywords bằng n-gram + stopwords Việt/Anh + tần suất.

    - Cụm 2–3 từ liên tiếp không chứa stopword/số được ưu tiên (score = freq × số từ).
    - Từ đơn chỉ được nhận khi dài ≥ 4 ký tự và xuất hiện ≥ 2 lần.
    - Cụm con của cụm dài đã chọn sẽ bị loại (tránh trùng lặp).
    """

    def extract(self, text: str, max_keywords: int = 12) -> list[str]:
        counter: Counter[str] = Counter()
        for sentence in _SENTENCE_SPLIT_RE.split(text):
            words = [w.lower() for w in _WORD_RE.findall(sentence)]
            content = [w if w not in _STOPWORDS else None for w in words]
            # n-gram 2..3 trên các "đoạn" từ liên tiếp không dính stopword
            run: list[str] = []
            runs: list[list[str]] = []
            for token in [*content, None]:
                if token is None:
                    if run:
                        runs.append(run)
                        run = []
                else:
                    run.append(token)
            for segment in runs:
                for size in (3, 2):
                    for i in range(len(segment) - size + 1):
                        counter[" ".join(segment[i : i + size])] += 1
                for word in segment:
                    if len(word) >= 4:
                        counter[word] += 1

        # Chấm điểm: tần suất × số từ (ưu tiên cụm dài); từ đơn cần freq ≥ 2
        scored: list[tuple[float, str]] = []
        for phrase, freq in counter.items():
            n_words = phrase.count(" ") + 1
            if n_words == 1 and freq < 2:
                continue
            scored.append((freq * n_words, phrase))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))

        keywords: list[str] = []
        for _, phrase in scored:
            # Bỏ cụm con nếu đã có cụm dài chứa nó (và ngược lại giữ cụm điểm cao trước)
            if any(phrase in kept or kept in phrase for kept in keywords):
                continue
            keywords.append(phrase)
            if len(keywords) >= max_keywords:
                break
        return keywords
