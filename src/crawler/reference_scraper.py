"""Thu thập trích dẫn. Phụ trách: Trần Nguyên Tân (24120438).

Các bước của `scrape_references_for_paper` (mỗi bước là một nhóm hàm bên dưới):
  1. Kiểm tra và chuẩn hóa ID bài nguồn; sai hình dạng thì lỗi ngay, chưa gửi request nào.
  2. Hỏi Semantic Scholar (S2). Request đầu lấy luôn danh sách trích dẫn; nếu S2 cắt bớt thì lấy lại
     bằng endpoint phân trang. Lỗi tạm thời (429, 5xx, mạng) được thử lại, chờ tăng dần.
  3. S2 trả 404 (không biết bài này) thì đọc .bib/.bbl trong thư mục nguồn đã giải nén.
  4. Đổi mọi thứ thành bản ghi chung (đúng các khóa của REFERENCE_KEYS) và bỏ cạnh trích dẫn trùng.

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

logger = logging.getLogger(__name__)

# Danh sách khóa của MỘT bản ghi trích dẫn mà hàm trả về: mỗi bản ghi có đúng các khóa này, không thừa không thiếu.
# Đây là "nguồn sự thật duy nhất" cho tên khóa: code tạo bản ghi, test và storage.py đều đọc từ đây.
# - 6 khóa đầu là cột bảng `references` theo đề M1, giữ đúng thứ tự:
#   https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/
# - 5 khóa sau là khóa nội bộ do Tân đề xuất, CHỜ Trí (storage.py) xác nhận.
# - Thiếu dữ liệu thì để None, riêng ref_authors để [] (danh sách rỗng); không bịa giá trị.
# Dùng tuple (không sửa được lúc chạy) để không đoạn code nào lỡ tay thêm/bớt khóa.
REFERENCE_KEYS: tuple[str, ...] = (
    # --- 6 cột của đề ---
    "arxiv_id",  # bài ĐANG trích dẫn (bài trong khoảng ID được giao), không có đuôi phiên bản
    "ref_arxiv_id",  # bài ĐƯỢC trích, lấy từ externalIds.ArXiv; None nếu tài liệu không có trên arXiv
    "ref_title",
    "ref_authors",  # list[str] tên tác giả, giữ thứ tự
    "ref_submission_date",  # lấy từ publicationDate của S2 ("YYYY-MM-DD"); không tự dựng từ năm
    "ref_s2_id",  # paperId của Semantic Scholar; thường None với mục S2 chưa nhận diện được
    # --- 5 khóa nội bộ (đề xuất) ---
    "ref_doi",  # DOI đã bỏ tiền tố "https://doi.org/" hoặc "doi:"
    "ref_year",  # int
    "ref_venue",  # chuỗi rỗng từ S2 coi là thiếu, đổi thành None
    "raw_citation",  # chuỗi gốc trong .bib/.bbl (nhánh dự phòng); None với bản ghi từ API
    "source",  # chỉ nhận "semantic_scholar" hoặc "bib_fallback"
)

# Hai giá trị hợp lệ của khóa "source".
_SOURCE_API = "semantic_scholar"
_SOURCE_BIB = "bib_fallback"


class ReferenceScrapeError(Exception):
    """Lỗi khi lấy trích dẫn của một bài: mạng hỏng, máy chủ lỗi, hết lượt thử lại, dữ liệu trả về hỏng.

    Ném lỗi thay vì trả [] để main.py phân biệt "bài bị lỗi" với "bài không trích dẫn ai".
    """


class PaperNotFoundError(ReferenceScrapeError):
    """Semantic Scholar trả 404 và không có file .bib/.bbl nào đọc được để dự phòng."""


# --- Cấu hình gọi Semantic Scholar -----------------------------------------------------------------
_API_BASE = "https://api.semanticscholar.org/graph/v1/paper"
# Trường của một trích dẫn. Phải là trường PHẲNG: đề không cho dùng dạng lồng như `authors.name`.
_REF_FIELDS = ("paperId", "title", "authors", "year", "publicationDate", "venue", "externalIds")
_PAGE_FIELDS = ",".join(_REF_FIELDS)  # cho endpoint /references (tên trường không có tiền tố)
_PAPER_FIELDS = "referenceCount," + ",".join(f"references.{name}" for name in _REF_FIELDS)
_PAGE_LIMIT = 1000  # S2 cho lấy tối đa 1000 mục mỗi trang /references
_TIMEOUT = (10, 60)  # (giây chờ kết nối, giây chờ đọc). Thiếu timeout thì mạng đứng là treo vô hạn.

# --- Thử lại khi lỗi tạm thời (giả định G4 ở đầu tests/test_reference_scraper.py) ----------------
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)
_MAX_ATTEMPTS = 6  # tổng số lần gửi một request: 1 lần đầu + 5 lần thử lại
_BACKOFF_BASE_SEC = 10.0  # lần chờ đầu; mỗi lần sau gấp đôi: 10, 20, 40, 80, 160 giây
_MAX_WAIT_SEC = 300.0  # trần cho MỖI lần chờ (5 phút), kể cả khi Retry-After đòi lâu hơn
_JITTER_FRACTION = 0.25  # cộng thêm ngẫu nhiên tối đa 25% để các tiến trình khỏi thử lại cùng một lúc

# Trạng thái ở mức module, dùng chung cho cả tiến trình (xem _get_session và _wait_for_rate_limit).
_session: requests.Session | None = None
_last_request_at: float | None = None  # mốc time.monotonic() của request gần nhất


def scrape_references_for_paper(
    arxiv_id: str,
    unzipped_paper_dir: str | None = None,
    rate_limit_sec: float = 3.1,
) -> list[dict]:
    """Lấy references qua Semantic Scholar, dự phòng bằng .bib/.bbl.

    Tham số:
      arxiv_id: ID bài nguồn. Nhận cả dạng có URL, tiền tố "arXiv:" hay đuôi "vN" và tự chuẩn hóa.
      unzipped_paper_dir: thư mục nguồn đã giải nén của bài. Chỉ được đọc khi S2 trả 404.
      rate_limit_sec: khoảng cách tối thiểu (giây) giữa hai request liên tiếp, tính chung cả tiến trình.

    Trả về list[dict]; mỗi phần tử là một cạnh trích dẫn với đúng các khóa của REFERENCE_KEYS, theo thứ tự
    S2 trả về. Khóa "source" cho biết bản ghi đến từ API hay từ .bib/.bbl. Danh sách rỗng [] CHỈ xuất hiện
    khi S2 trả 200 và bài thật sự không có trích dẫn nào.

    Ngoại lệ:
      TypeError, ValueError: arxiv_id hoặc rate_limit_sec sai (chưa gửi request nào).
      PaperNotFoundError: S2 trả 404 và không có .bib/.bbl dùng được.
      ReferenceScrapeError: mọi lỗi còn lại (mạng, 429/5xx hết lượt thử lại, mã 4xx khác, dữ liệu hỏng).
    """
    source_id = _validate_source_id(arxiv_id)
    if not math.isfinite(rate_limit_sec) or rate_limit_sec < 0:
        raise ValueError(f"rate_limit_sec phải là số không âm, nhận {rate_limit_sec!r}")

    try:
        refs = _fetch_s2_references(source_id, rate_limit_sec)
    except PaperNotFoundError as not_found:
        # Chỉ 404 mới dẫn tới dự phòng. Lỗi tạm thời (429, 5xx, mạng) đã được thử lại rồi ném lên,
        # không bao giờ chạy tới đây, nếu không dữ liệu dự phòng sẽ che mất lỗi.
        records = _read_local_references(source_id, unzipped_paper_dir)
        if not records:
            raise PaperNotFoundError(f"{not_found}; không có .bib/.bbl dùng được trong thư mục nguồn") from not_found
        return records
    return _dedupe([_record_from_s2(source_id, ref) for ref in refs])


# =================================================================================================
# 1. Chuẩn hóa ID arXiv và DOI
# =================================================================================================

# ID arXiv có hai kiểu (https://info.arxiv.org/help/arxiv_identifier.html):
#   mới: YYMM.NNNN hoặc YYMM.NNNNN, ví dụ 2407.12839
#   cũ : archive/YYMMNNN, ví dụ hep-th/9901001 hoặc math.GT/0309136
_ARXIV_ID_PATTERN = r"[0-9]{4}\.[0-9]{4,5}|[a-z]+(?:-[a-z]+)*(?:\.[A-Za-z]{2})?/[0-9]{7}"

# Khớp TOÀN BỘ chuỗi (fullmatch): [URL hoặc "arXiv:"] + ID + ["vN"] + [".pdf"]. Chỉ phần tiền tố bỏ qua hoa/thường,
# còn ID giữ nguyên (math.GT có chữ hoa thật). Nhóm số 1 là ID.
_ARXIV_ID_RE = re.compile(
    r"(?:(?i:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:))?"
    rf"({_ARXIV_ID_PATTERN})"
    r"(?:v[0-9]+)?(?:\.pdf)?"
)

# DOI có dạng 10.<mã nhà xuất bản>/<hậu tố>. Khớp toàn bộ chuỗi, cho phép tiền tố URL hoặc "doi:". Nhóm số 1 là DOI.
_DOI_RE = re.compile(r"(?:(?i:https?://(?:dx\.)?doi\.org/|doi:\s*))?(10\.[^\s/]+/\S+)")

# Tìm ID/DOI nằm TRONG chuỗi trích dẫn tự do (.bbl, trường url/note của .bib). ID arXiv bắt buộc có dấu hiệu
# đi kèm ("arXiv:", "arxiv.org/abs/", hoặc "abs/" kiểu CoRR) nên số vu vơ như "1234.5678" không bị nhận nhầm.
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
    """Bỏ tiền tố URL hoặc "doi:" khỏi DOI, giữ nguyên hoa/thường; không phải DOI thì None."""
    if not isinstance(value, str):
        return None
    match = _DOI_RE.fullmatch(value.strip())
    return match.group(1) if match else None


def _trim_trailing_punctuation(text: str) -> str:
    """Bỏ dấu câu dính ở cuối ID do nằm cuối câu, ví dụ "10.1000/abc." hay "(doi:10.1000/abc)"."""
    text = text.rstrip(".,;:")
    while text.endswith(")") and text.count(")") > text.count("("):  # chỉ bỏ ")" thừa, giữ ")" thuộc DOI
        text = text[:-1].rstrip(".,;:")
    return text


def _find_arxiv_id(text: str) -> str | None:
    """ID arXiv đầu tiên có dấu hiệu rõ ràng trong chuỗi tự do; không có thì None (không đoán)."""
    match = _ARXIV_IN_TEXT_RE.search(text)
    return match.group(1) if match else None


def _find_doi(text: str) -> str | None:
    """DOI đầu tiên trong chuỗi tự do, đã bỏ dấu câu cuối; không có thì None."""
    match = _DOI_IN_TEXT_RE.search(text)
    if match is None:
        return None
    return _normalize_doi(_trim_trailing_punctuation(match.group()))


def _validate_source_id(arxiv_id: object) -> str:
    """ID bài nguồn đã chuẩn hóa. Sai kiểu hoặc sai hình dạng thì lỗi NGAY, trước khi gửi request.

    Kiểm chặt vì ID được ghép vào URL: chuỗi như "2407.12839?fields=x" hay "../x" không được lọt qua.
    """
    if not isinstance(arxiv_id, str):
        raise TypeError(f"arxiv_id phải là chuỗi, nhận {type(arxiv_id).__name__}")
    normalized = _normalize_arxiv_id(arxiv_id)
    if normalized is None:
        raise ValueError(f"arxiv_id không đúng dạng ID arXiv: {arxiv_id!r}")
    return normalized


# =================================================================================================
# 2. Gọi HTTP: Session dùng chung, giới hạn tốc độ, thử lại có chờ tăng dần
# =================================================================================================


def _get_session() -> requests.Session:
    """MỘT Session dùng chung cả tiến trình: giữ kết nối mở, khỏi bắt tay lại với server ở mỗi request."""
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _api_headers() -> dict[str, str]:
    """Header xác thực. Khóa chỉ đọc từ biến môi trường S2_API_KEY, MỖI LẦN gọi (không đọc lúc import).

    Khóa chỉ đi bằng header, không bao giờ vào URL, log hay thông điệp lỗi. Không có khóa thì trả {}:
    vẫn chạy được ở chế độ không khóa (hạn mức chung, chậm hơn).
    """
    key = os.environ.get("S2_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}


def _wait_for_rate_limit(rate_limit_sec: float) -> None:
    """Ngủ vừa đủ để hai request liên tiếp cách nhau ít nhất rate_limit_sec giây, rồi ghi mốc cho request sắp gửi.

    Mốc _last_request_at nằm ở mức module nên bộ giới hạn dùng chung cả tiến trình: gọi cho bài khác vẫn nối tiếp
    mốc của bài trước. Chỉ ngủ phần CÒN THIẾU (thời gian tải/giải nén đã trôi qua thì không ngủ thêm), khác với
    `sleep` cứng sau mỗi lệnh. Hàm này được gọi trước MỌI request, kể cả trang sau và lần thử lại.
    Giả định chạy tuần tự, đúng với `main.py` (không dùng nhiều luồng).
    """
    global _last_request_at
    now = time.monotonic()
    if _last_request_at is not None:
        remaining = _last_request_at + rate_limit_sec - now
        if remaining > 0:
            time.sleep(remaining)
            now = time.monotonic()
    _last_request_at = now


def _parse_retry_after(value: str | None) -> float | None:
    """Đọc header Retry-After dạng số giây (RFC 9110, mục 10.2.3). Hỏng hay không có thì None.

    "Hỏng" gồm chữ, rỗng, số âm, NaN, vô cực. Dạng ngày giờ HTTP (ví dụ "Wed, 21 Oct 2026 07:28:00 GMT")
    chưa được hỗ trợ và cũng cho None; khi đó dùng backoff thay thế.
    """
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _backoff_seconds(attempt: int, retry_after: float | None) -> float:
    """Số giây chờ trước lần thử kế tiếp (attempt = số lần đã gửi, bắt đầu từ 1).

    Server đã nói phải chờ bao lâu (Retry-After) thì nghe theo. Nếu không thì exponential backoff (chờ gấp đôi
    sau mỗi lần) cộng jitter (lệch ngẫu nhiên nhỏ). Lần chờ nào cũng có trần _MAX_WAIT_SEC.
    Ý tưởng jitter: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
    """
    if retry_after is not None:
        return min(retry_after, _MAX_WAIT_SEC)
    delay = _BACKOFF_BASE_SEC * 2 ** (attempt - 1)
    delay += random.uniform(0, delay * _JITTER_FRACTION)
    return min(delay, _MAX_WAIT_SEC)


def _get_json(url: str, params: dict, source_id: str, rate_limit_sec: float) -> object:
    """GET một URL của S2 và trả về JSON đã giải mã, thử lại khi gặp lỗi tạm thời.

    - 200: trả JSON. Nội dung không phải JSON thì ReferenceScrapeError, không thử lại.
    - 404: PaperNotFoundError. Đây là câu trả lời dứt khoát nên không thử lại.
    - 429, 5xx, lỗi mạng: chờ rồi thử lại, tối đa _MAX_ATTEMPTS lần; hết lượt thì ReferenceScrapeError.
    - mã khác (400, 401, 403...): ReferenceScrapeError ngay, vì thử lại cũng vô ích.
    """
    session = _get_session()
    headers = _api_headers()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        _wait_for_rate_limit(rate_limit_sec)
        retry_after = None
        cause = None
        try:
            response = session.get(url, params=params, headers=headers, timeout=_TIMEOUT)
        except _TRANSIENT_ERRORS as exc:
            problem, cause = f"lỗi mạng {type(exc).__name__}", exc
        except requests.exceptions.RequestException as exc:
            # Lỗi kiểu URL sai, chuyển hướng vô tận...: thử lại không giúp gì. Chỉ ghi tên lỗi, không ghi nội dung.
            raise ReferenceScrapeError(
                f"Request tới S2 cho bài {source_id} thất bại, không thử lại được: {type(exc).__name__}"
            ) from exc
        else:
            status = response.status_code
            if status == 200:
                return _decode_json(response, source_id)
            if status == 404:
                raise PaperNotFoundError(f"S2 không có bài {source_id} (HTTP 404)")
            if status not in _RETRY_STATUSES:
                raise ReferenceScrapeError(f"S2 trả HTTP {status} cho bài {source_id}")
            problem = f"HTTP {status}"
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))

        if attempt == _MAX_ATTEMPTS:
            raise ReferenceScrapeError(
                f"S2 vẫn lỗi sau {_MAX_ATTEMPTS} lần thử cho bài {source_id} (lần cuối: {problem})"
            ) from cause
        wait = _backoff_seconds(attempt, retry_after)
        logger.warning(
            "S2 lỗi (%s) cho bài %s, thử lại lần %d/%d sau %.1f giây",
            problem, source_id, attempt, _MAX_ATTEMPTS - 1, wait,
        )
        if wait > 0:  # Retry-After: 0 nghĩa là không cần chờ thêm; bộ giới hạn tốc độ vẫn tự chờ nếu cần
            time.sleep(wait)


def _decode_json(response: requests.Response, source_id: str) -> object:
    """Giải mã thân phản hồi 200; không phải JSON hợp lệ (HTML của gateway, rỗng, bị cắt) thì báo lỗi."""
    try:
        return response.json()
    except ValueError as exc:
        raise ReferenceScrapeError(f"S2 trả nội dung không phải JSON cho bài {source_id}") from exc


# =================================================================================================
# 3. Lấy trích dẫn từ Semantic Scholar (kể cả khi bị cắt bớt)
# =================================================================================================


def _fetch_s2_references(source_id: str, rate_limit_sec: float) -> list[dict]:
    """Toàn bộ trích dẫn thô (dict kiểu S2) của bài. PaperNotFoundError nếu S2 không có bài này.

    Request đầu (`/paper/arXiv:{id}`) lấy cả danh sách trích dẫn trong một lần, nhanh nhất. Nhưng S2 có thể cắt
    bớt, nên so với referenceCount (tổng thật): đủ thì dùng luôn, thiếu (hoặc không biết tổng) thì bỏ danh sách đó
    và lấy lại từ đầu bằng endpoint phân trang. Bỏ hẳn thay vì nối tiếp vì chưa chắc hai endpoint cùng thứ tự.
    """
    paper_url = f"{_API_BASE}/arXiv:{quote(source_id, safe='')}"
    body = _get_json(paper_url, {"fields": _PAPER_FIELDS}, source_id, rate_limit_sec)
    refs = body.get("references") if isinstance(body, dict) else None
    if not isinstance(refs, list):
        raise ReferenceScrapeError(f"S2 trả dữ liệu sai hình dạng cho bài {source_id}: thiếu danh sách references")
    total = body.get("referenceCount")
    if isinstance(total, int) and not isinstance(total, bool) and len(refs) >= total:
        return refs
    return _fetch_s2_pages(f"{paper_url}/references", source_id, rate_limit_sec)


def _fetch_s2_pages(url: str, source_id: str, rate_limit_sec: float) -> list[dict]:
    """Đi hết các trang của endpoint /references, theo đúng `next` mà S2 báo (không tự đoán theo limit)."""
    refs: list[dict] = []
    offset = 0
    while True:
        params = {"fields": _PAGE_FIELDS, "offset": offset, "limit": _PAGE_LIMIT}
        try:
            page = _get_json(url, params, source_id, rate_limit_sec)
        except PaperNotFoundError as exc:
            # Request đầu đã tìm thấy bài mà trang sau lại 404: S2 tự mâu thuẫn. Đây là lỗi, KHÔNG được coi là
            # "bài không có trên S2" (nếu không sẽ rơi vào nhánh dự phòng và che mất lỗi).
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
        if next_offset is None:  # không còn trang sau
            return refs
        # Chống vòng lặp vô hạn khi S2 phân trang lỗi: `next` phải tiến lên và trang phải có dữ liệu.
        if not isinstance(next_offset, int) or isinstance(next_offset, bool) or next_offset <= offset or not data:
            raise ReferenceScrapeError(
                f"Phân trang của S2 không tiến cho bài {source_id} (offset={offset}, next={next_offset!r})"
            )
        offset = next_offset


# =================================================================================================
# 4. Đổi dữ liệu thô thành bản ghi
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
    """Dựng MỘT bản ghi đủ 11 khóa của REFERENCE_KEYS. Thiếu dữ liệu thì None (riêng tác giả thì [])."""
    return {
        "arxiv_id": arxiv_id,
        "ref_arxiv_id": ref_arxiv_id,
        "ref_title": ref_title,
        "ref_authors": list(ref_authors) if ref_authors else [],  # luôn là list MỚI, không dùng chung giữa các bản ghi
        "ref_submission_date": ref_submission_date,
        "ref_s2_id": ref_s2_id,
        "ref_doi": ref_doi,
        "ref_year": ref_year,
        "ref_venue": ref_venue,
        "raw_citation": raw_citation,
        "source": source,
    }


def _clean_text(value: object) -> str | None:
    """Giữ NGUYÊN chuỗi gốc; không phải chuỗi, rỗng hoặc toàn khoảng trắng thì coi là thiếu (None)."""
    return value if isinstance(value, str) and value.strip() else None


def _s2_author_names(authors: object) -> list[str]:
    """Tên các tác giả theo thứ tự của S2; bỏ mục không có tên."""
    if not isinstance(authors, list):
        return []
    return [a["name"] for a in authors if isinstance(a, dict) and _clean_text(a.get("name"))]


def _record_from_s2(source_id: str, ref: object) -> dict:
    """Một mục trích dẫn của S2 thành một bản ghi. Khóa nào S2 bỏ hẳn hay để null thì cho None, không bịa."""
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
        ref_submission_date=_clean_text(ref.get("publicationDate")),  # chỉ lấy nguyên văn, không dựng từ năm
        ref_s2_id=_clean_text(ref.get("paperId")),
        ref_doi=_normalize_doi(external_ids.get("DOI")),
        ref_year=year if isinstance(year, int) and not isinstance(year, bool) else None,
        ref_venue=_clean_text(ref.get("venue")),
    )


# =================================================================================================
# 5. Bỏ cạnh trích dẫn trùng
# =================================================================================================


def _normalize_title(title: str | None) -> str:
    """Dạng so sánh của tiêu đề: thường hóa, bỏ dấu câu và ngoặc, gộp khoảng trắng. CHỈ dùng để so trùng."""
    if not title:
        return ""
    folded = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(re.sub(r"\W+", " ", folded).split())


def _dedupe_key(record: dict) -> tuple | None:
    """Khóa nhận diện một cạnh trích dẫn: ID arXiv; không có thì ID S2; không có nữa thì (tiêu đề chuẩn hóa, năm).

    Không dựng được khóa nào (không ID, không tiêu đề) thì None: không đủ cơ sở để nói hai mục là một.
    """
    if record["ref_arxiv_id"]:
        return ("arxiv", record["ref_arxiv_id"])
    if record["ref_s2_id"]:
        return ("s2", record["ref_s2_id"])
    title = _normalize_title(record["ref_title"])
    return ("title", title, record["ref_year"]) if title else None


def _dedupe(records: list[dict]) -> list[dict]:
    """Mỗi cạnh (bài nguồn, tài liệu được trích) chỉ một dòng: giữ dòng xuất hiện đầu, các dòng còn lại giữ thứ tự.

    Tập `seen` là biến cục bộ nên chỉ chống trùng trong MỘT bài; hai bài cùng trích một tài liệu vẫn mỗi bài một dòng.
    """
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
# 6. Dự phòng: đọc .bib / .bbl trong thư mục nguồn đã giải nén
# =================================================================================================
# Chỉ được gọi khi S2 trả 404. Bóc được trường nào thì lấy trường đó, KHÔNG đoán phần còn lại; chuỗi gốc luôn
# được giữ trong `raw_citation`. Định dạng BibTeX: http://www.bibtex.org/Format/

_BRACE_RE = re.compile(r"[{}]")
_QUOTE_SCAN_RE = re.compile(r'[{}"]')
# Đầu một mục: "@loại{" nằm đầu dòng (cho phép thụt lề). Dùng để cắt file thành từng khối, nhờ vậy một mục
# thiếu ngoặc đóng chỉ làm mất chính nó chứ không nuốt cả các mục phía sau.
_BIB_LINE_START_RE = re.compile(r"^[ \t]*@(?=[A-Za-z]+\s*\{)", re.MULTILINE)
_BIB_HEAD_RE = re.compile(r"@([A-Za-z]+)\s*\{")
# Tên trường kiểu `title =`. Lookbehind buộc phải bắt đầu ở đầu từ để regex không thử lại ở từng chữ cái của
# một chuỗi chữ dài (tránh chậm bậc hai).
_BIB_FIELD_NAME_RE = re.compile(r"(?<![A-Za-z0-9_:\-])([A-Za-z][A-Za-z0-9_:\-]*)\s*=\s*")
_BIB_BARE_RE = re.compile(r'[^\s,{}"#]+')
_BIB_AND_RE = re.compile(r"[{}]|(?<=\s)and(?=\s)", re.IGNORECASE)
_BIB_YEAR_RE = re.compile(r"[0-9]{4}(?![0-9])")
_BIB_SKIPPED_KINDS = frozenset({"string", "preamble", "comment"})  # không phải trích dẫn

_BIBITEM_RE = re.compile(r"\\bibitem\b")
_BIBITEM_HEAD_RE = re.compile(r"\s*(?:\[[^\]]*\])?\s*\{[^}]*\}")  # phần "[nhãn]{khóa}" ngay sau \bibitem
_END_BIBLIOGRAPHY = "\\end{thebibliography}"


def _read_local_references(source_id: str, unzipped_paper_dir: str | None) -> list[dict]:
    """Bản ghi dự phòng đọc từ .bib/.bbl trong thư mục (kể cả thư mục con); không có gì dùng được thì [].

    Quy tắc chọn (giả định của Tân, CHƯA chốt với nhóm): ưu tiên .bib vì có trường có cấu trúc; chỉ khi không
    có mục .bib nào mới dùng .bbl. Không trộn cả hai vì cùng một tài liệu sẽ bị tính hai lần.
    """
    if unzipped_paper_dir is None:
        return []
    root = Path(unzipped_paper_dir)
    if not root.is_dir():
        return []
    # Bỏ symlink để một file trong gói giải nén không thể trỏ ra ngoài thư mục. Sắp xếp để kết quả ổn định.
    files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    for suffix, parse in ((".bib", _bib_records), (".bbl", _bbl_records)):
        records: list[dict] = []
        for path in files:
            if path.suffix.lower() == suffix:
                records.extend(parse(source_id, _read_text(path)))
        if records:
            logger.info("Dùng %s dự phòng cho bài %s: %d mục", suffix, source_id, len(records))
            return _dedupe(records)
    return []


def _read_text(path: Path) -> str:
    """Đọc file văn bản. Thử UTF-8 (tự bỏ BOM đầu file); không được thì Latin-1, đọc được mọi byte nên không lỗi."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReferenceScrapeError(f"Không đọc được file nguồn {path.name}: {exc.strerror or type(exc).__name__}") from exc
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


# --- .bib ------------------------------------------------------------------------------------------


def _find_closing_brace(text: str, open_index: int) -> int:
    """Vị trí dấu } khớp với dấu { ở open_index (đếm ngoặc lồng nhau). Không khớp thì -1."""
    depth = 0
    for match in _BRACE_RE.finditer(text, open_index):
        depth += 1 if match.group() == "{" else -1
        if depth == 0:
            return match.start()
    return -1


def _split_bib_entries(text: str) -> Iterator[tuple[str, str]]:
    """Duyệt các mục `@loại{...}`; mỗi lần trả (loại viết thường, chuỗi gốc của cả mục).

    Cắt file thành khối ở mỗi "@loại{" đầu dòng rồi mới ghép ngoặc TRONG từng khối, nên thời gian chạy tỉ lệ với
    kích thước file và mục hỏng (thiếu ngoặc đóng) chỉ mất riêng nó. Trong một khối vẫn tìm tiếp các mục
    cùng dòng, ví dụ `@a{...}@b{...}`.
    """
    starts = [m.start() for m in _BIB_LINE_START_RE.finditer(text)]
    for i, start in enumerate(starts):
        chunk = text[start : starts[i + 1] if i + 1 < len(starts) else len(text)]
        pos = 0
        while True:
            head = _BIB_HEAD_RE.search(chunk, pos)
            if head is None:
                break
            end = _find_closing_brace(chunk, head.end() - 1)
            if end == -1:  # mục không đóng: bỏ phần còn lại của khối
                break
            yield head.group(1).lower(), chunk[head.start() : end + 1]
            pos = end + 1


def _read_bib_value(text: str, pos: int) -> tuple[str | None, int]:
    """Đọc giá trị của một trường bắt đầu ở pos; trả (giá trị hoặc None, vị trí ngay sau giá trị).

    Hỗ trợ `{...}` (ngoặc lồng nhau), `"..."` và số trần như `2019`. Tên macro như `jfix` (định nghĩa bằng
    @string) trả None: không tự suy ra nội dung, vì đoán sai là bịa dữ liệu.
    """
    if pos >= len(text):
        return None, pos
    char = text[pos]
    if char == "{":
        end = _find_closing_brace(text, pos)
        if end == -1:
            return None, len(text)
        return text[pos + 1 : end], end + 1
    if char == '"':
        depth = 0  # dấu " nằm trong {...} không kết thúc chuỗi
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
    """Các cặp `tên = giá trị` của một mục (tên viết thường). Trường lặp thì giữ lần đầu."""
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
    """Gộp khoảng trắng và xuống dòng thành một dấu cách (giá trị trong .bib hay bị ngắt dòng); rỗng thì None."""
    return " ".join(value.split()) or None if value else None


def _bib_authors(value: str | None) -> list[str]:
    """Tách trường author theo chữ "and" nằm NGOÀI ngoặc nhọn, nên tên tập thể {A and B} không bị tách.

    Giữ nguyên dạng "Họ, Tên" như trong file (không đảo), bỏ "others" (nghĩa là "và cộng sự").
    """
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
    """Năm lấy từ `year`, không có thì từ `date` (dạng 2021-03-04). Chỉ nhận 4 chữ số đứng đầu, không đoán."""
    for name in ("year", "date"):
        match = _BIB_YEAR_RE.match(fields.get(name, "").strip())
        if match:
            return int(match.group())
    return None


def _bib_arxiv_id(fields: dict[str, str], raw: str) -> str | None:
    """ID arXiv của một mục .bib. Chấp nhận `eprint` KHI archivePrefix (hoặc eprinttype) ghi rõ là arXiv,
    nếu không thì chỉ lấy khi chuỗi gốc có dấu hiệu rõ ràng ("arXiv:...", URL arxiv.org). Còn lại là None."""
    prefix = (fields.get("archiveprefix") or fields.get("eprinttype") or "").strip().lower()
    if prefix == "arxiv":
        found = _normalize_arxiv_id(fields.get("eprint"))
        if found:
            return found
    return _find_arxiv_id(raw)


def _record_from_bib_entry(source_id: str, raw: str) -> dict:
    """Một mục .bib thành một bản ghi; `raw_citation` là chuỗi gốc của cả mục."""
    head = _BIB_HEAD_RE.match(raw)
    body = raw[head.end() : -1]  # bỏ "@loại{" ở đầu và "}" ở cuối
    _, _, rest = body.partition(",")  # phần trước dấu phẩy đầu tiên là khóa trích dẫn, không dùng tới
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


def _bib_records(source_id: str, text: str) -> list[dict]:
    return [
        _record_from_bib_entry(source_id, raw)
        for kind, raw in _split_bib_entries(text)
        if kind not in _BIB_SKIPPED_KINDS
    ]


# --- .bbl ------------------------------------------------------------------------------------------


def _split_bbl_items(text: str) -> list[str]:
    """Cắt .bbl thành từng mục `\\bibitem`; trả phần chữ trích dẫn (bỏ dòng `\\bibitem[nhãn]{khóa}`
    và `\\end{thebibliography}`). Mục trống bị bỏ."""
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
    """Mỗi mục .bbl là chuỗi tự do nên CHỈ bóc ID arXiv và DOI; tiêu đề, tác giả, năm để None (không đoán)."""
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
