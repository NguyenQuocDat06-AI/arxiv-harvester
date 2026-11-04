"""Thu thập references từ Semantic Scholar, dự phòng bằng BibTeX khi S2 trả 404.

Phụ trách: Trần Nguyên Tân (24120438).
API: https://api.semanticscholar.org/api-docs/graph
"""

import logging
import math
import os
import random
import re
import time
import unicodedata
from collections.abc import Iterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import dotenv_values

from .exceptions import (
    CrawlerError,
    NetworkTimeoutError,
    RateLimitError,
)
from .rate_limiter import rate_limiter
from .request_policy import CooldownDeferred

logger = logging.getLogger(__name__)

# Sáu khóa đầu dùng cho course export; các khóa còn lại dùng nội bộ.
REFERENCE_KEYS: tuple[str, ...] = (
    "arxiv_id",             # Base ID của bài trích dẫn.
    "ref_arxiv_id",         # externalIds.ArXiv của tài liệu được trích.
    "ref_title",
    "ref_authors",
    "ref_submission_date",  # S2 publicationDate; không suy ngày từ năm.
    "ref_s2_id",            # Semantic Scholar paperId.

    "ref_doi",              # DOI đã bỏ tiền tố URL hoặc doi:.
    "ref_year",
    "ref_venue",
    "raw_citation",         # Nội dung BibTeX gốc khi dùng fallback.
    "source",
)


_SOURCE_API = "semantic_scholar"
_SOURCE_BIB = "bib_fallback"


# Lỗi truy vấn references.
class ReferenceScrapeError(CrawlerError):
    """Lỗi mạng, API hoặc dữ liệu trích dẫn."""


class PaperNotFoundError(ReferenceScrapeError):
    """S2 trả 404; caller có thể thử nguồn BibTeX local."""


class ReferencesUnavailableError(ReferenceScrapeError):
    """S2 báo có references nhưng trả danh sách rỗng."""


class BatchRequestSizeError(ReferenceScrapeError):
    """Batch response exceeds the API size limit."""


class SemanticScholarRateLimitError(RateLimitError, ReferenceScrapeError):
    """Hết lượt thử lại khi S2 trả HTTP 429."""


class SemanticScholarConnectionError(NetworkTimeoutError, ReferenceScrapeError):
    """Hết lượt thử lại khi gặp lỗi mạng/timeout tới S2."""


# Kết quả và trạng thái truy vấn.
class ReferenceResult(list):
    """Danh sách references kèm trạng thái và số đo request.

    success/empty/partial: kết quả S2 đầy đủ, rỗng hoặc thiếu.
    bib_fallback/not_indexed: S2 trả 404, có hoặc thiếu BibTeX dự phòng.
    unavailable/api_error: S2 trả rỗng bất thường hoặc truy vấn thất bại.
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
        request_metrics: dict | None = None,
        request_group: str | None = None,
        request_group_size: int = 1,
    ) -> None:
        super().__init__(records or [])
        self.status = status
        self.source = source
        self.expected_count = expected_count
        self.received_count = len(self) if received_count is None else received_count
        self.request_stats = dict(request_stats or {})
        self.error_message = error_message
        self.request_metrics = request_metrics
        self.request_group = request_group
        self.request_group_size = request_group_size

    def __repr__(self) -> str:
        return (
            f"ReferenceResult(len={len(self)}, status={self.status!r}, "
            f"source={self.source!r}, expected={self.expected_count}, received={self.received_count})"
        )


# Cấu hình gọi Semantic Scholar
_API_BASE = "https://api.semanticscholar.org/graph/v1/paper"
# Các trường phẳng của S2 Graph API.
_REF_FIELDS = ("paperId", "title", "authors", "year", "publicationDate", "venue", "externalIds")
_PAGE_FIELDS = ",".join(_REF_FIELDS)
_PAPER_FIELDS = "externalIds,referenceCount," + ",".join(f"references.{name}" for name in _REF_FIELDS)
_PAGE_LIMIT = 1000
_TIMEOUT = (10, 60)

# Lỗi có thể retry.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SEC = 5.0
_MAX_WAIT_SEC = 120.0
_JITTER_FRACTION = 0.25

_session: requests.Session | None = None
_cooldown_sec = 60.0
_cooldown_until = 0.0


def configure_request_policy(max_attempts: int = 3, cooldown_sec: float = 60.0) -> None:
    """Set bounded retries and reset pacing for a new run."""
    global _MAX_ATTEMPTS, _cooldown_sec, _cooldown_until
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("S2 max_attempts must be a positive integer")
    if not math.isfinite(cooldown_sec) or cooldown_sec < 0:
        raise ValueError("S2 cooldown_sec must be finite and nonnegative")
    _MAX_ATTEMPTS, _cooldown_sec = max_attempts, cooldown_sec
    _cooldown_until = 0.0
    if rate_limiter.policy.directory is None:
        for key in list(rate_limiter.policy.memory):
            if key.startswith("semantic_scholar"):
                del rate_limiter.policy.memory[key]


def _new_request_stats() -> dict:
    """Tạo bộ đếm request."""
    return {
        "requests": 0,
        "by_status": {},
        "by_method": {},
        "retries": 0,
        "backoff_sec": 0.0,
        "rate_limit_wait_sec": 0.0,
        "s2_404": 0,
        "partials": 0,
        "bib_fallbacks": 0,
        "empty_refs": 0,
        "deferred_queries": 0,
    }


_request_stats: dict = _new_request_stats()


def _count_request(key: str, method: str = "GET") -> None:
    _request_stats["requests"] += 1
    _request_stats["by_status"][key] = _request_stats["by_status"].get(key, 0) + 1
    _request_stats["by_method"][method] = _request_stats["by_method"].get(method, 0) + 1


def reset_request_stats() -> None:
    """Đặt lại bộ đếm request."""
    global _request_stats
    _request_stats = _new_request_stats()


def get_request_stats() -> dict:
    """Lấy bản sao bộ đếm request."""
    stats = dict(_request_stats)
    stats["by_status"] = dict(_request_stats["by_status"])
    stats["by_method"] = dict(_request_stats["by_method"])
    return stats


# API công khai.
def scrape_references_for_paper(
    arxiv_id: str,
    unzipped_paper_dir: str | None = None,
    rate_limit_sec: float = 3.1,
    raise_on_error: bool = False,
    raise_on_not_found: bool | None = None,
) -> ReferenceResult:
    """Lấy references từ S2; thử BibTeX local khi S2 trả 404.

    raise_on_error=True ném lỗi; mặc định trả ReferenceResult kèm status.
    raise_on_not_found là bí danh tương thích của raise_on_error.
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
            expected_count=None,
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


# Chuẩn hóa ID arXiv và DOI


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
    """Bỏ URL, tiền tố và version; trả None nếu ID không hợp lệ."""
    if not isinstance(value, str):
        return None
    match = _ARXIV_ID_RE.fullmatch(value.strip())
    return match.group(1) if match else None


def _normalize_doi(value: object) -> str | None:
    """Chuẩn hóa DOI; trả None nếu không hợp lệ."""
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


# HTTP session, rate limit và retry.


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _api_headers() -> dict[str, str]:
    key = os.environ.get("S2_API_KEY")
    if key is None:
        env_path = Path(__file__).resolve().parents[2] / ".env"
        key = dotenv_values(env_path, interpolate=False, encoding="utf-8-sig").get("S2_API_KEY")
    key = (key or "").strip()
    return {"x-api-key": key} if key else {}


def _wait_for_rate_limit(rate_limit_sec: float) -> None:
    """Chờ theo rate limit của Semantic Scholar."""
    t0 = time.monotonic()
    rate_limiter.wait("semantic_scholar", interval=rate_limit_sec)
    waited = time.monotonic() - t0
    if waited > 0.001:
        _request_stats["rate_limit_wait_sec"] += waited


def _parse_retry_after(value: str | None) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _backoff_seconds(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return retry_after
    delay = _BACKOFF_BASE_SEC * (2 ** (attempt - 1))
    delay += random.uniform(0, delay * _JITTER_FRACTION)
    return min(delay, _MAX_WAIT_SEC)


def _get_json(url: str, params: dict, source_id: str, rate_limit_sec: float,
              method: str = "GET", json_body: dict | None = None) -> object:
    global _cooldown_until
    remaining = _cooldown_until - time.monotonic()
    if _MAX_ATTEMPTS == 1:
        remaining = max(remaining, rate_limiter.policy.snapshot("semantic_scholar")["remaining_sec"])
    if remaining > 0:
        _request_stats["deferred_queries"] += 1
        raise SemanticScholarRateLimitError(
            f"S2 đang nghỉ sau HTTP 429; bài {source_id} cần thử lại, còn {remaining:.0f} giây",
            status_code=429, retry_after=remaining, failed_ids=[source_id],
        )
    session = _get_session()
    headers = _api_headers()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            _wait_for_rate_limit(rate_limit_sec)
        except CooldownDeferred as error:
            _request_stats["deferred_queries"] += 1
            raise SemanticScholarRateLimitError(str(error), retry_after=error.retry_after, failed_ids=[source_id]) from error
        retry_after = None
        cause = None
        try:
            if method == "POST":
                response = session.post(url, params=params, json=json_body, headers=headers, timeout=_TIMEOUT)
            else:
                response = session.get(url, params=params, headers=headers, timeout=_TIMEOUT)
        except _TRANSIENT_ERRORS as exc:
            _count_request("network", method)
            problem, cause = f"lỗi mạng {type(exc).__name__}", exc
        except requests.exceptions.RequestException as exc:
            _count_request("network", method)
            raise SemanticScholarConnectionError(
                f"Request tới S2 cho bài {source_id} thất bại: {type(exc).__name__}",
                timeout=_TIMEOUT[1],
                endpoint=url,
                failed_ids=[source_id],
            ) from exc
        else:
            status = response.status_code
            _count_request(str(status), method)
            if status == 200:
                rate_limiter.policy.succeeded("semantic_scholar")
                return _decode_json(response, source_id)
            if status == 404:
                _request_stats["s2_404"] = _request_stats.get("s2_404", 0) + 1
                raise PaperNotFoundError(f"S2 không có bài {source_id} (HTTP 404)")
            if method == "POST" and status in (400, 413, 422):
                try:
                    message = str(response.json()).lower()
                except ValueError:
                    message = ""
                if status == 413 or any(word in message for word in ("too large", "10 mb", "10mb", "size limit", "response size")):
                    raise BatchRequestSizeError(f"S2 batch vượt giới hạn kích thước (HTTP {status})")
            if status not in _RETRY_STATUSES:
                raise ReferenceScrapeError(f"S2 trả HTTP {status} cho bài {source_id}")
            problem = f"HTTP {status}"
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            if status == 429:
                retry_after = rate_limiter.policy.limited("semantic_scholar", response,
                                                         floor=_cooldown_sec, secrets=tuple(headers.values()))
                if retry_after > rate_limiter.policy.max_wait_sec:
                    _cooldown_until = time.monotonic() + retry_after
                    raise SemanticScholarRateLimitError(
                        f"S2 yêu cầu nghỉ {retry_after:.0f} giây; bài {source_id} cần thử lại",
                        status_code=429, retry_after=retry_after, failed_ids=[source_id],
                    )

        if attempt == _MAX_ATTEMPTS:
            if cause is not None:
                raise SemanticScholarConnectionError(
                    f"S2 lỗi mạng sau {_MAX_ATTEMPTS} lần thử cho bài {source_id}: {problem}",
                    timeout=_TIMEOUT[1],
                    endpoint=url,
                    failed_ids=[source_id],
                ) from cause
            if "429" in problem:
                _cooldown_until = time.monotonic() + max(_cooldown_sec, retry_after or 0.0)
                raise SemanticScholarRateLimitError(
                    f"S2 rate limit sau {_MAX_ATTEMPTS} lần thử cho bài {source_id}",
                    status_code=429,
                    retry_after=retry_after,
                    failed_ids=[source_id],
                )
            raise ReferenceScrapeError(
                f"S2 vẫn lỗi sau {_MAX_ATTEMPTS} lần thử cho bài {source_id} (lần cuối: {problem})"
            ) from cause

        wait = retry_after if "429" in problem and retry_after is not None else _backoff_seconds(attempt, retry_after)
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


# Truy vấn và phân trang S2.


def _fetch_s2_references(source_id: str, rate_limit_sec: float) -> tuple[list[dict], str, int | None]:
    """Trả về (references, status, expected_count) từ S2."""
    paper_url = f"{_API_BASE}/arXiv:{quote(source_id, safe='')}"
    body = _get_json(paper_url, {"fields": _PAPER_FIELDS}, source_id, rate_limit_sec)
    external = body.get("externalIds") if isinstance(body, dict) else None
    returned_id = external.get("ArXiv") if isinstance(external, dict) else None
    if returned_id is not None and _normalize_arxiv_id(returned_id) != source_id:
        raise ReferenceScrapeError(f"S2 trả ID bài nguồn khác yêu cầu {source_id}")
    refs = body.get("references") if isinstance(body, dict) else None
    if not isinstance(refs, list):
        raise ReferenceScrapeError(f"S2 trả dữ liệu sai hình dạng cho bài {source_id}: thiếu danh sách references")

    total = body.get("referenceCount")
    known_total = isinstance(total, int) and not isinstance(total, bool)
    if known_total and (total < 0 or (total == 0 and refs)):
        raise ReferenceScrapeError(f"S2 trả referenceCount mâu thuẫn với references của bài {source_id}")

    if known_total and total == 0:
        _request_stats["empty_refs"] = _request_stats.get("empty_refs", 0) + 1
        return [], "empty", 0

    if known_total and len(refs) >= total:
        return refs, "success", total

    # Lấy đủ trang nếu kết quả đầu bị cắt bớt.
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
    """Đọc references theo cursor next."""
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


# Đổi dữ liệu thô thành bản ghi chuẩn


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
    """Chuẩn hóa một reference theo REFERENCE_KEYS."""
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


# Khử trùng cạnh trích dẫn


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


# BibTeX fallback khi S2 trả 404.


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
    """Lấy citation keys trong TeX; '*' tương ứng với \\nocite{*}."""
    keys: set[str] = set()
    for text in tex_texts:
        for match in _TEX_CITE_RE.finditer(_TEX_COMMENT_RE.sub("", text)):
            if "cite" in match.group(1).lower():
                keys.update(key.strip() for key in match.group(2).split(",") if key.strip())
    return keys


def _read_local_references(source_id: str, unzipped_paper_dir: str | None) -> list[dict]:
    """Đọc các mục BibTeX được TeX trích dẫn."""
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
    print("Reference scraper tests")

    # Kiểm tra giao diện list của ReferenceResult.
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
    print(f"  ReferenceResult repr: {res}")
    print(f"  List interface verified.")

    # Kiểm tra lọc citation keys trong BibTeX.
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
    print(f"  Correctly extracted and filtered 1 cited entry out of {len(entries)}.")

    # Kiểm tra truy vấn S2.
    print("\n3. Test scrape_references_for_paper on real arXiv ID (2412.18848):")
    try:
        t0 = time.time()
        result = scrape_references_for_paper("2412.18848", rate_limit_sec=1.0)
        dt = time.time() - t0
        print(f"  Scraped in {dt:.2f}s: status={result.status}, source={result.source}, count={len(result)}")
        if result:
            print(f"  Sample ref 1: title='{result[0].get('ref_title')}', arxiv='{result[0].get('ref_arxiv_id')}'")
        stats = get_request_stats()
        print(f"  Request stats: {stats}")
    except Exception as exc:
        print(f"  [-] Network or S2 error in live test: {exc}")

    print("\nReference scraper tests completed.")
