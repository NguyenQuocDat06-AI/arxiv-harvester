"""Thu thập trích dẫn. Phụ trách: Trần Nguyên Tân (24120438).

Các bước của `scrape_references_for_paper`:
  1. Kiểm tra và chuẩn hóa ID bài nguồn; sai hình dạng thì lỗi ngay, chưa gửi request nào.
  2. Hỏi Semantic Scholar (S2). Request đầu lấy luôn danh sách trích dẫn; nếu S2 cắt bớt thì lấy lại
     bằng endpoint phân trang. Lỗi tạm thời (429, 5xx, mạng) được thử lại có chờ tăng dần (backoff + jitter).
  3. S2 trả 404 (không biết bài này) thì đọc .bib trong thư mục nguồn đã giải nén (chỉ lấy mục mà .tex trích).
  4. Đổi mọi thứ thành bản ghi chung (đúng các khóa của REFERENCE_KEYS) và bỏ cạnh trích dẫn trùng.
  5. Đóng gói vào ReferenceResult (kế thừa list) mang status ("success", "empty", "partial", "not_indexed", "bib_fallback", "api_error"),
     bảo đảm không bao giờ làm rơi metadata bài báo ở main pipeline.

Tài liệu API: https://api.semanticscholar.org/api-docs/graph
"""

import logging
import math
import os
import random
import re
import time
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import requests

from src.crawler.exceptions import (
    CrawlerError,
    NetworkTimeoutError,
    RateLimitError,
)
from src.crawler.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Danh sách khóa của MỘT bản ghi trích dẫn mà hàm trả về:
# - 6 khóa đầu là cột bảng `references` theo đề M1:
#   https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/
# - 5 khóa sau là khóa nội bộ phục vụ phân tích / audit / fallback.
REFERENCE_KEYS: tuple[str, ...] = (
    # --- 6 cột của đề ---
    "arxiv_id",             # bài ĐANG trích dẫn (base ID, không có đuôi vN)
    "ref_arxiv_id",         # bài ĐƯỢC trích, lấy từ externalIds.ArXiv; None nếu tài liệu không có trên arXiv
    "ref_title",
    "ref_authors",          # list[str] tên tác giả, giữ thứ tự
    "ref_submission_date",  # lấy từ publicationDate của S2 ("YYYY-MM-DD"); không tự dựng từ năm
    "ref_s2_id",            # paperId của Semantic Scholar; None với mục S2 chưa nhận diện được
    # --- 5 khóa nội bộ ---
    "ref_doi",              # DOI đã bỏ tiền tố "https://doi.org/" hoặc "doi:"
    "ref_year",             # int
    "ref_venue",            # chuỗi rỗng từ S2 coi là thiếu, đổi thành None
    "raw_citation",         # chuỗi gốc trong .bib/.bbl (nhánh dự phòng); None với bản ghi từ API
    "source",               # "semantic_scholar" hoặc "bib_fallback"
)

# Hai giá trị hợp lệ của khóa "source".
_SOURCE_API = "semantic_scholar"
_SOURCE_BIB = "bib_fallback"


# =================================================================================================
# Ngoại lệ đặc tả cho scraper trích dẫn
# =================================================================================================


class ReferenceScrapeError(CrawlerError):
    """Lỗi khi lấy trích dẫn của một bài: mạng hỏng, máy chủ lỗi, hết lượt thử lại, dữ liệu trả về hỏng."""


class PaperNotFoundError(ReferenceScrapeError):
    """Semantic Scholar trả 404 và không có file .bib/.bbl nào đọc được để dự phòng."""


class ReferencesUnavailableError(ReferenceScrapeError):
    """S2 có bài và báo có trích dẫn (referenceCount > 0) nhưng không đưa mục nào."""


class SemanticScholarRateLimitError(RateLimitError, ReferenceScrapeError):
    """Hết lượt thử lại khi S2 trả HTTP 429."""


class SemanticScholarConnectionError(NetworkTimeoutError, ReferenceScrapeError):
    """Hết lượt thử lại khi gặp lỗi mạng/timeout tới S2."""


# =================================================================================================
# Cấu trúc kết quả trích dẫn: ReferenceResult
# =================================================================================================


class ReferenceResult(list):
    """Danh sách kết quả trích dẫn kế thừa list để tương thích 100% với list[dict],
    đồng thời mang metadata trạng thái: status, source, expected_count, received_count, request_stats.

    Các trạng thái:
      - "success": Lấy thành công đầy đủ trích dẫn từ S2.
      - "empty": S2 xác nhận bài không có trích dẫn (referenceCount = 0).
      - "partial": S2 trả về một phần trích dẫn (ít hơn referenceCount công bố).
      - "bib_fallback": Không có trên S2 (404), đã trích xuất từ .bib được .tex trích dẫn.
      - "not_indexed": S2 trả 404 và không có .bib dự phòng.
      - "unavailable": S2 báo có trích dẫn nhưng trả về rỗng.
      - "api_error": Lỗi mạng/API hoặc 429 quá số lần thử lại.
    """

    def __init__(
        self,
        records: list[dict] | None = None,
        status: str = "success",
        source: str = _SOURCE_API,
        expected_count: int | None = None,
        received_count: int | None = None,
        request_stats: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        super().__init__(records or [])
        self.status = status
        self.source = source
        self.expected_count = expected_count
        self.received_count = len(self) if received_count is None else received_count
        self.request_stats = dict(request_stats or {})
        self.error_message = error_message

    def __repr__(self) -> str:
        return (
            f"ReferenceResult(len={len(self)}, status={self.status!r}, "
            f"source={self.source!r}, expected={self.expected_count}, received={self.received_count})"
        )


# --- Cấu hình gọi Semantic Scholar -----------------------------------------------------------------
_API_BASE = "https://api.semanticscholar.org/graph/v1/paper"
# Trường của một trích dẫn. Phải là trường phẳng theo đặc tả S2 Graph API.
_REF_FIELDS = ("paperId", "title", "authors", "year", "publicationDate", "venue", "externalIds")
_PAGE_FIELDS = ",".join(_REF_FIELDS)
_PAPER_FIELDS = "referenceCount," + ",".join(f"references.{name}" for name in _REF_FIELDS)
_PAGE_LIMIT = 1000
_TIMEOUT = (10, 60)

# Thử lại khi lỗi tạm thời (429, 5xx, timeout, ngắt kết nối)
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)
_MAX_ATTEMPTS = 6
_BACKOFF_BASE_SEC = 5.0
_MAX_WAIT_SEC = 120.0
_JITTER_FRACTION = 0.25

_session: requests.Session | None = None


def _new_request_stats() -> dict:
    """Bộ đếm thống kê cho báo cáo Chương 03 và kiểm toán dữ liệu."""
    return {
        "requests": 0,
        "by_status": {},
        "retries": 0,
        "backoff_sec": 0.0,
        "rate_limit_wait_sec": 0.0,
        "s2_404": 0,
        "partials": 0,
        "bib_fallbacks": 0,
        "empty_refs": 0,
    }


_request_stats: dict = _new_request_stats()


def _count_request(key: str) -> None:
    _request_stats["requests"] += 1
    _request_stats["by_status"][key] = _request_stats["by_status"].get(key, 0) + 1


def reset_request_stats() -> None:
    """Đặt bộ đếm về 0 khi bắt đầu chạy một phân vùng mới hoặc trong test."""
    global _request_stats
    _request_stats = _new_request_stats()


def get_request_stats() -> dict:
    """Bản sao snapshot của bộ đếm hiện tại."""
    stats = dict(_request_stats)
    stats["by_status"] = dict(_request_stats["by_status"])
    return stats


# =================================================================================================
# Hàm giao diện chính
# =================================================================================================


def scrape_references_for_paper(
    arxiv_id: str,
    unzipped_paper_dir: str | None = None,
    rate_limit_sec: float = 3.1,
    raise_on_error: bool = False,
    raise_on_not_found: bool | None = None,
) -> ReferenceResult:
    """Lấy references qua Semantic Scholar, dự phòng bằng .bib trong thư mục nguồn đã giải nén.

    Tham số:
      arxiv_id: ID bài nguồn (nhận cả dạng '2407.12839', 'arXiv:2407.12839v2', URL...).
      unzipped_paper_dir: thư mục nguồn đã giải nén của bài (chỉ dùng đọc .bib khi S2 trả 404).
      rate_limit_sec: khoảng cách tối thiểu (giây) giữa 2 request S2 (mặc định 3.1s cho hạn mức public).
      raise_on_error: nếu True, ném ngoại lệ khi gặp lỗi mạng/404/không có trích dẫn.
                      nếu False (mặc định cho pipeline), trả ReferenceResult với status tương ứng để
                      pipeline KHÔNG bao giờ làm rơi bài báo khỏi publications.parquet.
      raise_on_not_found: bí danh tương thích cho raise_on_error khi xử lý 404.

    Trả về:
      ReferenceResult (kế thừa list[dict]): danh sách các cạnh trích dẫn theo REFERENCE_KEYS,
      kèm các thuộc tính: status, source, expected_count, received_count, request_stats.
    """
    if raise_on_not_found is not None:
        raise_on_error = raise_on_not_found

    source_id = _validate_source_id(arxiv_id)
    if not math.isfinite(rate_limit_sec) or rate_limit_sec < 0:
        raise ValueError(f"rate_limit_sec phải là số không âm, nhận {rate_limit_sec!r}")

    try:
        refs, status, expected_count = _fetch_s2_references(source_id, rate_limit_sec)
        records = _dedupe([_record_from_s2(source_id, ref) for ref in refs])
        return ReferenceResult(
            records,
            status=status,
            source=_SOURCE_API,
            expected_count=expected_count,
            received_count=len(records),
            request_stats=get_request_stats(),
        )
    except PaperNotFoundError as not_found:
        local_records = _read_local_references(source_id, unzipped_paper_dir)
        if local_records:
            _request_stats["bib_fallbacks"] = _request_stats.get("bib_fallbacks", 0) + 1
            return ReferenceResult(
                local_records,
                status="bib_fallback",
                source=_SOURCE_BIB,
                expected_count=len(local_records),
                received_count=len(local_records),
                request_stats=get_request_stats(),
            )
        if raise_on_error:
            raise PaperNotFoundError(f"{not_found}; không có .bib dùng được trong thư mục nguồn") from not_found
        return ReferenceResult(
            [],
            status="not_indexed",
            source="none",
            expected_count=0,
            received_count=0,
            request_stats=get_request_stats(),
            error_message=str(not_found),
        )
    except ReferencesUnavailableError as unavail:
        if raise_on_error:
            raise
        return ReferenceResult(
            [],
            status="unavailable",
            source=_SOURCE_API,
            expected_count=None,
            received_count=0,
            request_stats=get_request_stats(),
            error_message=str(unavail),
        )
    except ReferenceScrapeError as err:
        if raise_on_error:
            raise
        logger.warning("Lỗi scrape references cho bài %s: %s", source_id, err)
        return ReferenceResult(
            [],
            status="api_error",
            source="none",
            expected_count=None,
            received_count=0,
            request_stats=get_request_stats(),
            error_message=str(err),
        )


# =================================================================================================
# 1. Chuẩn hóa ID arXiv và DOI
# =================================================================================================

_ARXIV_ID_PATTERN = r"[0-9]{4}\.[0-9]{4,5}|[a-z]+(?:-[a-z]+)*(?:\.[A-Za-z]{2})?/[0-9]{7}"

_ARXIV_ID_RE = re.compile(
    r"(?:(?i:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:))?"
    rf"({_ARXIV_ID_PATTERN})"
    r"(?:v[0-9]+)?(?:\.pdf)?"
)

_DOI_RE = re.compile(r"(?:(?i:https?://(?:dx\.)?doi\.org/|doi:\s*))?(10\.[^\s/]+/\S+)")

_ARXIV_IN_TEXT_RE = re.compile(
    r"(?:(?i:arxiv\.org/(?:abs|pdf)/|arxiv\s*:\s*)|(?<![A-Za-z0-9])abs/)"
    rf"({_ARXIV_ID_PATTERN})(?![0-9])"
)
_DOI_IN_TEXT_RE = re.compile(r"(?<![A-Za-z0-9])10\.[0-9]{4,9}/[^\s{}<>\"',;]+")


def _normalize_arxiv_id(value: object) -> str | None:
    """Đưa ID arXiv về dạng chuẩn (không URL, không tiền tố, không đuôi vN); không phải ID thì None."""
    if not isinstance(value, str):
        return None
    match = _ARXIV_ID_RE.fullmatch(value.strip())
    return match.group(1) if match else None


def _normalize_doi(value: object) -> str | None:
    """Bỏ tiền tố URL hoặc 'doi:' khỏi DOI; không phải DOI thì None."""
    if not isinstance(value, str):
        return None
    match = _DOI_RE.fullmatch(value.strip())
    return match.group(1) if match else None


def _trim_trailing_punctuation(text: str) -> str:
    text = text.rstrip(".,;:")
    while text.endswith(")") and text.count(")") > text.count("("):
        text = text[:-1].rstrip(".,;:")
    return text


def _find_arxiv_id(text: str) -> str | None:
    match = _ARXIV_IN_TEXT_RE.search(text)
    return match.group(1) if match else None


def _find_doi(text: str) -> str | None:
    match = _DOI_IN_TEXT_RE.search(text)
    if match is None:
        return None
    return _normalize_doi(_trim_trailing_punctuation(match.group()))


def _validate_source_id(arxiv_id: object) -> str:
    if not isinstance(arxiv_id, str):
        raise TypeError(f"arxiv_id phải là chuỗi, nhận {type(arxiv_id).__name__}")
    normalized = _normalize_arxiv_id(arxiv_id)
    if normalized is None:
        raise ValueError(f"arxiv_id không đúng dạng ID arXiv: {arxiv_id!r}")
    return normalized


# =================================================================================================
# 2. Gọi HTTP: Session, rate limit, exponential backoff + jitter
# =================================================================================================


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _api_headers() -> dict[str, str]:
    key = os.environ.get("S2_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}


def _wait_for_rate_limit(rate_limit_sec: float) -> None:
    """Giới hạn tốc độ sử dụng DomainRateLimiter cho domain 'semantic_scholar'."""
    t0 = time.monotonic()
    rate_limiter.wait("semantic_scholar", interval=rate_limit_sec)
    waited = time.monotonic() - t0
    if waited > 0.001:
        _request_stats["rate_limit_wait_sec"] += waited


def _parse_retry_after(value: str | None) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _backoff_seconds(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, _MAX_WAIT_SEC)
    delay = _BACKOFF_BASE_SEC * (2 ** (attempt - 1))
    delay += random.uniform(0, delay * _JITTER_FRACTION)
    return min(delay, _MAX_WAIT_SEC)


def _get_json(url: str, params: dict, source_id: str, rate_limit_sec: float) -> object:
    session = _get_session()
    headers = _api_headers()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        _wait_for_rate_limit(rate_limit_sec)
        retry_after = None
        cause = None
        try:
            response = session.get(url, params=params, headers=headers, timeout=_TIMEOUT)
        except _TRANSIENT_ERRORS as exc:
            _count_request("network")
            problem, cause = f"lỗi mạng {type(exc).__name__}", exc
        except requests.exceptions.RequestException as exc:
            _count_request("network")
            raise SemanticScholarConnectionError(
                f"Request tới S2 cho bài {source_id} thất bại: {type(exc).__name__}",
                timeout=_TIMEOUT[1],
                endpoint=url,
                failed_ids=[source_id],
            ) from exc
        else:
            status = response.status_code
            _count_request(str(status))
            if status == 200:
                return _decode_json(response, source_id)
            if status == 404:
                _request_stats["s2_404"] = _request_stats.get("s2_404", 0) + 1
                raise PaperNotFoundError(f"S2 không có bài {source_id} (HTTP 404)")
            if status not in _RETRY_STATUSES:
                raise ReferenceScrapeError(f"S2 trả HTTP {status} cho bài {source_id}")
            problem = f"HTTP {status}"
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))

        if attempt == _MAX_ATTEMPTS:
            if cause is not None:
                raise SemanticScholarConnectionError(
                    f"S2 lỗi mạng sau {_MAX_ATTEMPTS} lần thử cho bài {source_id}: {problem}",
                    timeout=_TIMEOUT[1],
                    endpoint=url,
                    failed_ids=[source_id],
                ) from cause
            if "429" in problem:
                raise SemanticScholarRateLimitError(
                    f"S2 rate limit sau {_MAX_ATTEMPTS} lần thử cho bài {source_id}",
                    status_code=429,
                    retry_after=retry_after,
                    failed_ids=[source_id],
                )
            raise ReferenceScrapeError(
                f"S2 vẫn lỗi sau {_MAX_ATTEMPTS} lần thử cho bài {source_id} (lần cuối: {problem})"
            ) from cause

        wait = _backoff_seconds(attempt, retry_after)
        _request_stats["retries"] += 1
        _request_stats["backoff_sec"] += wait
        logger.warning(
            "S2 lỗi (%s) cho bài %s, thử lại lần %d/%d sau %.1f giây",
            problem, source_id, attempt, _MAX_ATTEMPTS - 1, wait,
        )
        if wait > 0:
            time.sleep(wait)


def _decode_json(response: requests.Response, source_id: str) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise ReferenceScrapeError(f"S2 trả nội dung không phải JSON cho bài {source_id}") from exc


# =================================================================================================
# 3. Lấy trích dẫn từ Semantic Scholar (hỗ trợ phân trang và phát hiện cắt bớt)
# =================================================================================================


def _fetch_s2_references(source_id: str, rate_limit_sec: float) -> tuple[list[dict], str, int | None]:
    """Toàn bộ trích dẫn thô từ Semantic Scholar.

    Trả về tuple: (danh_sách_refs, status, expected_count).
    Status có thể là: 'success', 'empty', 'partial'.
    """
    paper_url = f"{_API_BASE}/arXiv:{quote(source_id, safe='')}"
    body = _get_json(paper_url, {"fields": _PAPER_FIELDS}, source_id, rate_limit_sec)
    refs = body.get("references") if isinstance(body, dict) else None
    if not isinstance(refs, list):
        raise ReferenceScrapeError(f"S2 trả dữ liệu sai hình dạng cho bài {source_id}: thiếu danh sách references")

    total = body.get("referenceCount")
    known_total = isinstance(total, int) and not isinstance(total, bool)

    if known_total and total == 0:
        _request_stats["empty_refs"] = _request_stats.get("empty_refs", 0) + 1
        return [], "empty", 0

    if known_total and len(refs) >= total:
        return refs, "success", total

    # Nếu S2 cắt bớt trong request đầu, gọi tiếp endpoint /references phân trang
    paged = _fetch_s2_pages(f"{paper_url}/references", source_id, rate_limit_sec)
    if len(paged) < len(refs):
        paged = refs

    if known_total and len(paged) < total:
        if not paged:
            raise ReferencesUnavailableError(f"S2 báo bài {source_id} có {total} trích dẫn nhưng không trả mục nào")
        logger.warning(
            "S2 báo bài %s có %d trích dẫn nhưng chỉ trả %d; đánh dấu partial", source_id, total, len(paged)
        )
        _request_stats["partials"] = _request_stats.get("partials", 0) + 1
        return paged, "partial", total

    return paged, "success", total if known_total else len(paged)


def _fetch_s2_pages(url: str, source_id: str, rate_limit_sec: float) -> list[dict]:
    """Duyệt hết các trang phân trang của S2 qua cursor next."""
    refs: list[dict] = []
    offset = 0
    while True:
        params = {"fields": _PAGE_FIELDS, "offset": offset, "limit": _PAGE_LIMIT}
        try:
            page = _get_json(url, params, source_id, rate_limit_sec)
        except PaperNotFoundError as exc:
            raise ReferenceScrapeError(f"Trang offset={offset} của bài {source_id} trả 404 dù bài tồn tại") from exc

        data = page.get("data") if isinstance(page, dict) else None
        if not isinstance(data, list):
            raise ReferenceScrapeError(f"S2 trả trang sai hình dạng cho bài {source_id} (offset={offset})")

        for item in data:
            cited = item.get("citedPaper") if isinstance(item, dict) else None
            if not isinstance(cited, dict):
                raise ReferenceScrapeError(f"S2 trả một mục thiếu citedPaper cho bài {source_id} (offset={offset})")
            refs.append(cited)

        next_offset = page.get("next")
        if next_offset is None:
            return refs

        if not isinstance(next_offset, int) or isinstance(next_offset, bool) or next_offset <= offset or not data:
            raise ReferenceScrapeError(
                f"Phân trang của S2 không tiến cho bài {source_id} (offset={offset}, next={next_offset!r})"
            )
        offset = next_offset


# =================================================================================================
# 4. Đổi dữ liệu thô thành bản ghi chuẩn
# =================================================================================================


def _make_record(
    arxiv_id: str,
    source: str,
    *,
    ref_arxiv_id: str | None = None,
    ref_title: str | None = None,
    ref_authors: list[str] | None = None,
    ref_submission_date: str | None = None,
    ref_s2_id: str | None = None,
    ref_doi: str | None = None,
    ref_year: int | None = None,
    ref_venue: str | None = None,
    raw_citation: str | None = None,
) -> dict:
    """Dựng MỘT bản ghi đúng 11 khóa của REFERENCE_KEYS."""
    return {
        "arxiv_id": arxiv_id,
        "ref_arxiv_id": ref_arxiv_id,
        "ref_title": ref_title,
        "ref_authors": list(ref_authors) if ref_authors else [],
        "ref_submission_date": ref_submission_date,
        "ref_s2_id": ref_s2_id,
        "ref_doi": ref_doi,
        "ref_year": ref_year,
        "ref_venue": ref_venue,
        "raw_citation": raw_citation,
        "source": source,
    }


def _clean_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _s2_author_names(authors: object) -> list[str]:
    if not isinstance(authors, list):
        return []
    return [a["name"] for a in authors if isinstance(a, dict) and _clean_text(a.get("name"))]


def _record_from_s2(source_id: str, ref: object) -> dict:
    if not isinstance(ref, dict):
        raise ReferenceScrapeError(f"S2 trả một mục trích dẫn không phải object cho bài {source_id}")
    external_ids = ref.get("externalIds")
    if not isinstance(external_ids, dict):
        external_ids = {}
    year = ref.get("year")
    return _make_record(
        source_id,
        _SOURCE_API,
        ref_arxiv_id=_normalize_arxiv_id(external_ids.get("ArXiv")),
        ref_title=_clean_text(ref.get("title")),
        ref_authors=_s2_author_names(ref.get("authors")),
        ref_submission_date=_clean_text(ref.get("publicationDate")),
        ref_s2_id=_clean_text(ref.get("paperId")),
        ref_doi=_normalize_doi(external_ids.get("DOI")),
        ref_year=year if isinstance(year, int) and not isinstance(year, bool) else None,
        ref_venue=_clean_text(ref.get("venue")),
    )


# =================================================================================================
# 5. Khử trùng cạnh trích dẫn
# =================================================================================================


def _normalize_title(title: str | None) -> str:
    if not title:
        return ""
    folded = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(re.sub(r"\W+", " ", folded).split())


def _dedupe_key(record: dict) -> tuple | None:
    if record["ref_arxiv_id"]:
        return ("arxiv", record["ref_arxiv_id"])
    if record["ref_s2_id"]:
        return ("s2", record["ref_s2_id"])
    title = _normalize_title(record["ref_title"])
    return ("title", title, record["ref_year"]) if title else None


def _dedupe(records: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    unique = []
    for record in records:
        key = _dedupe_key(record)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        unique.append(record)
    return unique


# =================================================================================================
# 6. Dự phòng: Đọc .bib trong thư mục nguồn khi S2 trả 404
# =================================================================================================

_BRACE_RE = re.compile(r"[{}]")
_QUOTE_SCAN_RE = re.compile(r'[{}"]')
_BIB_LINE_START_RE = re.compile(r"^[ \t]*@(?=[A-Za-z]+\s*\{)", re.MULTILINE)
_BIB_HEAD_RE = re.compile(r"@([A-Za-z]+)\s*\{")
_BIB_FIELD_NAME_RE = re.compile(r"(?<![A-Za-z0-9_:\-])([A-Za-z][A-Za-z0-9_:\-]*)\s*=\s*")
_BIB_BARE_RE = re.compile(r'[^\s,{}"#]+')
_BIB_AND_RE = re.compile(r"[{}]|(?<=\s)and(?=\s)", re.IGNORECASE)
_BIB_YEAR_RE = re.compile(r"[0-9]{4}(?![0-9])")
_BIB_SKIPPED_KINDS = frozenset({"string", "preamble", "comment"})

_BIBITEM_RE = re.compile(r"\\bibitem\b")
_BIBITEM_HEAD_RE = re.compile(r"\s*(?:\[[^\]]*\])?\s*\{[^}]*\}")
_END_BIBLIOGRAPHY = "\\end{thebibliography}"

_TEX_COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")
_TEX_CITE_RE = re.compile(r"\\([A-Za-z]+)\*?\s*(?:\[[^\[\]{}]{0,500}\]\s*){0,2}\{([^{}]*)\}")


def _cited_keys(tex_texts: list[str]) -> set[str]:
    """Tìm các khóa BibTeX mà các file .tex trích dẫn; '*' nghĩa là \\nocite{*}."""
    keys: set[str] = set()
    for text in tex_texts:
        for match in _TEX_CITE_RE.finditer(_TEX_COMMENT_RE.sub("", text)):
            if "cite" in match.group(1).lower():
                keys.update(key.strip() for key in match.group(2).split(",") if key.strip())
    return keys


def _read_local_references(source_id: str, unzipped_paper_dir: str | None) -> list[dict]:
    """Đọc bản ghi trích dẫn từ .bib trong thư mục đã giải nén (chỉ lấy mục mà .tex trích dẫn)."""
    if unzipped_paper_dir is None:
        return []
    root = Path(unzipped_paper_dir)
    if not root.is_dir():
        return []

    files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    bib_files = [p for p in files if p.suffix.lower() == ".bib"]
    if bib_files:
        cited = _cited_keys([_read_text(p) for p in files if p.suffix.lower() == ".tex"])
        entries = [entry for path in bib_files for entry in _bib_entries(source_id, _read_text(path))]
        kept = [record for key, record in entries if "*" in cited or key in cited]
        if kept:
            logger.info("Dùng .bib dự phòng cho bài %s: giữ %d/%d mục được trích", source_id, len(kept), len(entries))
            return _dedupe(kept)

    bbl_records: list[dict] = []
    for path in files:
        if path.suffix.lower() == ".bbl":
            bbl_records.extend(_bbl_records(source_id, _read_text(path)))
    if bbl_records:
        logger.info("Dùng .bbl dự phòng cho bài %s: %d mục", source_id, len(bbl_records))
        return _dedupe(bbl_records)

    return []


def _read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReferenceScrapeError(f"Không đọc được file nguồn {path.name}: {exc.strerror or type(exc).__name__}") from exc
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _find_closing_brace(text: str, open_index: int) -> int:
    depth = 0
    for match in _BRACE_RE.finditer(text, open_index):
        depth += 1 if match.group() == "{" else -1
        if depth == 0:
            return match.start()
    return -1


def _split_bib_entries(text: str) -> Iterator[tuple[str, str]]:
    starts = [m.start() for m in _BIB_LINE_START_RE.finditer(text)]
    for i, start in enumerate(starts):
        chunk = text[start : starts[i + 1] if i + 1 < len(starts) else len(text)]
        pos = 0
        while True:
            head = _BIB_HEAD_RE.search(chunk, pos)
            if head is None:
                break
            end = _find_closing_brace(chunk, head.end() - 1)
            if end == -1:
                break
            yield head.group(1).lower(), chunk[head.start() : end + 1]
            pos = end + 1


def _read_bib_value(text: str, pos: int) -> tuple[str | None, int]:
    if pos >= len(text):
        return None, pos
    char = text[pos]
    if char == "{":
        end = _find_closing_brace(text, pos)
        if end == -1:
            return None, len(text)
        return text[pos + 1 : end], end + 1
    if char == '"':
        depth = 0
        for match in _QUOTE_SCAN_RE.finditer(text, pos + 1):
            token = match.group()
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
            elif depth <= 0:
                return text[pos + 1 : match.start()], match.end()
        return None, len(text)
    bare = _BIB_BARE_RE.match(text, pos)
    if bare is None:
        return None, pos + 1
    return (bare.group() if bare.group().isdigit() else None), bare.end()


def _parse_bib_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    pos = 0
    while True:
        name = _BIB_FIELD_NAME_RE.search(text, pos)
        if name is None:
            return fields
        value, pos = _read_bib_value(text, name.end())
        if value is not None:
            fields.setdefault(name.group(1).lower(), value)


def _collapse_spaces(value: str | None) -> str | None:
    return " ".join(value.split()) or None if value else None


def _bib_authors(value: str | None) -> list[str]:
    if not value:
        return []
    pieces, depth, start = [], 0, 0
    for match in _BIB_AND_RE.finditer(value):
        token = match.group()
        if token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
        elif depth == 0:
            pieces.append(value[start : match.start()])
            start = match.end()
    pieces.append(value[start:])
    names = (" ".join(piece.split()) for piece in pieces)
    return [name for name in names if name and name.lower() != "others"]


def _bib_year(fields: dict[str, str]) -> int | None:
    for name in ("year", "date"):
        match = _BIB_YEAR_RE.match(fields.get(name, "").strip())
        if match:
            return int(match.group())
    return None


def _bib_arxiv_id(fields: dict[str, str], raw: str) -> str | None:
    prefix = (fields.get("archiveprefix") or fields.get("eprinttype") or "").strip().lower()
    if prefix == "arxiv":
        found = _normalize_arxiv_id(fields.get("eprint"))
        if found:
            return found
    return _find_arxiv_id(raw)


def _record_from_bib_entry(source_id: str, raw: str) -> dict:
    head = _BIB_HEAD_RE.match(raw)
    if head is None:
        return _make_record(source_id, _SOURCE_BIB, raw_citation=raw)
    body = raw[head.end() : -1]
    _, _, rest = body.partition(",")
    fields = _parse_bib_fields(rest)
    return _make_record(
        source_id,
        _SOURCE_BIB,
        ref_arxiv_id=_bib_arxiv_id(fields, raw),
        ref_title=_collapse_spaces(fields.get("title")),
        ref_authors=_bib_authors(fields.get("author")),
        ref_doi=_normalize_doi(fields.get("doi")) or _find_doi(raw),
        ref_year=_bib_year(fields),
        ref_venue=_collapse_spaces(fields.get("journal")) or _collapse_spaces(fields.get("booktitle")),
        raw_citation=raw,
    )


def _bib_entry_key(raw: str) -> str:
    head = _BIB_HEAD_RE.match(raw)
    if head is None:
        return ""
    body = raw[head.end() : -1]
    return body.partition(",")[0].strip()


def _bib_entries(source_id: str, text: str) -> list[tuple[str, dict]]:
    return [
        (_bib_entry_key(raw), _record_from_bib_entry(source_id, raw))
        for kind, raw in _split_bib_entries(text)
        if kind not in _BIB_SKIPPED_KINDS
    ]


def _split_bbl_items(text: str) -> list[str]:
    marks = list(_BIBITEM_RE.finditer(text))
    items = []
    for i, mark in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[mark.end() : stop].split(_END_BIBLIOGRAPHY, 1)[0]
        head = _BIBITEM_HEAD_RE.match(body)
        if head:
            body = body[head.end() :]
        body = body.strip()
        if body:
            items.append(body)
    return items


def _bbl_records(source_id: str, text: str) -> list[dict]:
    return [
        _make_record(
            source_id,
            _SOURCE_BIB,
            ref_arxiv_id=_find_arxiv_id(item),
            ref_doi=_find_doi(item),
            raw_citation=item,
        )
        for item in _split_bbl_items(text)
    ]


if __name__ == "__main__":
    print("=== TEST REFERENCE SCRAPER ===")

    # 1. Test ReferenceResult dataclass / list interface
    print("\n1. Test ReferenceResult class:")
    sample_records = [
        _make_record("2412.18848", _SOURCE_API, ref_arxiv_id="1706.03762", ref_title="Attention Is All You Need"),
        _make_record("2412.18848", _SOURCE_API, ref_arxiv_id="1810.04805", ref_title="BERT"),
    ]
    res = ReferenceResult(sample_records, status="success", source="semantic_scholar", expected_count=2)
    assert isinstance(res, list), "ReferenceResult must inherit list"
    assert len(res) == 2, f"Expected length 2, got {len(res)}"
    assert res.status == "success"
    assert res[0]["ref_title"] == "Attention Is All You Need"
    print(f"  [+] ReferenceResult repr: {res}")
    print(f"  [+] List iteration and indexing working properly.")

    # 2. Test BibTeX extraction and cite filtering
    print("\n2. Test BibTeX cite matching:")
    bib_sample = """
    @article{vaswani2017,
        title = {Attention is All You Need},
        author = {Vaswani, Ashish and Shazeer, Noam},
        journal = {NeurIPS},
        year = {2017},
        eprint = {1706.03762},
        archivePrefix = {arXiv}
    }
    @article{devlin2018,
        title = {BERT: Pre-training of Deep Bidirectional Transformers},
        author = {Devlin, Jacob and Chang, Ming-Wei},
        year = {2018}
    }
    """
    tex_sample = "We use the Transformer architecture \\cite{vaswani2017} as baseline."
    cited = _cited_keys([tex_sample])
    assert "vaswani2017" in cited
    assert "devlin2018" not in cited

    entries = _bib_entries("2412.18848", bib_sample)
    filtered = [rec for key, rec in entries if key in cited]
    assert len(filtered) == 1
    assert filtered[0]["ref_arxiv_id"] == "1706.03762"
    assert filtered[0]["ref_year"] == 2017
    print(f"  [+] Correctly extracted and filtered 1 cited entry out of {len(entries)}.")

    # 3. Test Live Query or Safe Error Handling
    print("\n3. Test scrape_references_for_paper on real arXiv ID (2412.18848):")
    try:
        t0 = time.time()
        result = scrape_references_for_paper("2412.18848", rate_limit_sec=1.0)
        dt = time.time() - t0
        print(f"  [+] Scraped in {dt:.2f}s: status={result.status}, source={result.source}, count={len(result)}")
        if result:
            print(f"  [+] Sample ref 1: title='{result[0].get('ref_title')}', arxiv='{result[0].get('ref_arxiv_id')}'")
        stats = get_request_stats()
        print(f"  [+] Request stats: {stats}")
    except Exception as exc:
        print(f"  [-] Network or S2 error in live test: {exc}")

    print("\n[+] Reference scraper testing completed successfully.")
