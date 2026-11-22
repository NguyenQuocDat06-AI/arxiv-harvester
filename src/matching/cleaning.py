"""Làm sạch và chuẩn hóa văn bản BibTeX / metadata trích dẫn cho Milestone 3."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "for", "of", "in", "on", "to", "with",
    "via", "by", "from", "at", "as", "into", "over", "under", "using",
    "based", "towards", "toward", "through", "between", "within", "without",
    "is", "are", "was", "were", "be", "been", "this", "that", "these", "those",
})

_ARXIV_NEW_RE = re.compile(
    r"(?:arxiv\s*[:/]\s*|arxiv\.org/(?:abs|pdf|src)/)?(\d{4}\.\d{4,5})(?:v\d+)?\b",
    re.IGNORECASE,
)
_ARXIV_OLD_RE = re.compile(
    r"(?:arxiv\s*[:/]\s*|arxiv\.org/(?:abs|pdf|src)/)?([a-z-]+(?:\.[a-z-]+)?/\d{7})(?:v\d+)?\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(19\d{2}|20[0-3]\d)\b")
_LATEX_CMD_ARG_RE = re.compile(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}")
_LATEX_ACCENT_SYM_RE = re.compile(r"\\[\"'\^`~=.]\s*\{?([a-zA-Z])\}?")
_LATEX_ACCENT_LET_RE = re.compile(r"\\[uvHcdbrkt](?:\s+|\{)([a-zA-Z])\}?")
_LATEX_CMD_BARE_RE = re.compile(r"\\[a-zA-Z]+\*?\s*")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_MULTI_SPACE_RE = re.compile(r"\s+")
_CITE_CMD_RE = re.compile(r"\\cite[a-zA-Z*]*\s*(?:\[[^\]]*\]\s*)*\{([^}]+)\}")


def fold_ascii(text: str) -> str:
    """Chuyển chuỗi Unicode có dấu thành chữ thường ASCII."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def strip_latex(text: str | None) -> str:
    """Loại bỏ macro LaTeX, dấu ngoặc nhọn và chuẩn hóa khoảng trắng."""
    if not text:
        return ""
    s = str(text)
    s = _LATEX_ACCENT_SYM_RE.sub(r"\1", s)
    s = _LATEX_ACCENT_LET_RE.sub(r"\1", s)
    # Gỡ tối đa 3 lớp lồng nhau như \textbf{\emph{...}}
    for _ in range(3):
        updated = _LATEX_CMD_ARG_RE.sub(r" \1 ", s)
        if updated == s:
            break
        s = updated
    s = _LATEX_CMD_BARE_RE.sub(" ", s)
    s = s.replace("{", " ").replace("}", " ").replace("~", " ").replace("$", " ")
    s = fold_ascii(s)
    return _MULTI_SPACE_RE.sub(" ", s).strip()


def normalize_title(text: str | None) -> str:
    """Chuẩn hóa tiêu đề: bỏ LaTeX, bỏ dấu câu và gộp khoảng trắng."""
    cleaned = strip_latex(text)
    if not cleaned:
        return ""
    cleaned = _NON_ALNUM_RE.sub(" ", cleaned)
    return _MULTI_SPACE_RE.sub(" ", cleaned).strip()


def tokenize_title(text: str | None, *, remove_stopwords: bool = True) -> list[str]:
    """Tách từ tiêu đề đã chuẩn hóa, tùy chọn loại stopword tiếng Anh."""
    norm = normalize_title(text)
    if not norm:
        return []
    tokens = norm.split()
    if remove_stopwords:
        filtered = [tok for tok in tokens if tok not in _STOPWORDS]
        if filtered:
            return filtered
    return tokens


def _split_author_string(raw: str) -> list[str]:
    parts = re.split(r"\s+and\s+|\s*;\s*|\s*&\s*", raw, flags=re.IGNORECASE)
    if len(parts) == 1 and parts[0].count(",") >= 2 and "et al" not in parts[0].lower():
        # Dạng "A. Smith, B. Jones, C. Lee"
        comma_parts = [p.strip() for p in parts[0].split(",") if p.strip()]
        if all(len(p.split()) >= 2 for p in comma_parts):
            return comma_parts
    return [p.strip() for p in parts if p.strip()]


def parse_author_surnames(authors: Any) -> list[tuple[str, str]]:
    """Trích danh sách (họ chuẩn hóa, chữ cái đầu tên) từ list hoặc chuỗi tác giả."""
    if authors is None:
        return []
    raw_items: list[str] = []
    if isinstance(authors, str):
        raw_items = _split_author_string(authors)
    elif isinstance(authors, (list, tuple)):
        for item in authors:
            if item is None:
                continue
            s = str(item).strip()
            if not s:
                continue
            if " and " in s.lower() or ";" in s:
                raw_items.extend(_split_author_string(s))
            else:
                raw_items.append(s)
    else:
        return []

    parsed: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_items:
        cleaned = strip_latex(item)
        cleaned = re.sub(r"\bet\s+al\.?", "", cleaned).strip()
        if not cleaned or cleaned in {"others", "et"}:
            continue
        if "," in cleaned:
            left, right = [part.strip() for part in cleaned.split(",", 1)]
            surname_tokens = _NON_ALNUM_RE.sub(" ", left).split()
            given_tokens = _NON_ALNUM_RE.sub(" ", right).split()
            surname = surname_tokens[-1] if surname_tokens else ""
            initial = given_tokens[0][0] if given_tokens else ""
        else:
            tokens = _NON_ALNUM_RE.sub(" ", cleaned).split()
            if not tokens:
                continue
            surname = tokens[-1]
            initial = tokens[0][0] if len(tokens) >= 2 else ""
        if not surname or len(surname) == 1:
            continue
        pair = (surname, initial)
        if pair not in seen:
            seen.add(pair)
            parsed.append(pair)
    return parsed


def extract_arxiv_id(*texts: Any) -> str | None:
    """Trích xuất arXiv ID chuẩn (bỏ hậu tố vN) từ URL, DOI hoặc chuỗi raw."""
    for raw in texts:
        if not raw:
            continue
        s = str(raw).strip()
        if not s:
            continue
        m_new = _ARXIV_NEW_RE.search(s)
        if m_new:
            return m_new.group(1)
        m_old = _ARXIV_OLD_RE.search(s)
        if m_old:
            return m_old.group(1).lower()
    return None


def extract_year(year_val: Any = None, *texts: Any) -> int | None:
    """Trích năm xuất bản hợp lệ (1900..2030) từ số nguyên hoặc chuỗi ngày/text."""
    if year_val is not None and not isinstance(year_val, bool):
        try:
            y = int(float(year_val))
            if 1900 <= y <= 2030:
                return y
        except (TypeError, ValueError):
            pass
    for raw in (year_val, *texts):
        if not raw:
            continue
        m = _YEAR_RE.search(str(raw))
        if m:
            y = int(m.group(1))
            if 1900 <= y <= 2030:
                return y
    return None


def extract_citation_keys_from_tex(text: str | None) -> list[str]:
    """Trích toàn bộ citation_key được gọi trong lệnh \\cite{...} của một đoạn TeX."""
    if not text:
        return []
    keys: list[str] = []
    for match in _CITE_CMD_RE.finditer(text):
        for raw_key in match.group(1).split(","):
            key = raw_key.strip()
            if key:
                keys.append(key)
    return keys
