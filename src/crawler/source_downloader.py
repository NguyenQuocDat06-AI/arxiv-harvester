"""Tải và dọn mã nguồn. Phụ trách: Nguyễn Đình Tuấn (24120237)."""

import concurrent.futures
import contextlib
import gzip
import http.client
import logging
import math
import os
import random
import re
import shutil
import tarfile
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import urllib3.exceptions
from requests.adapters import HTTPAdapter

from .rate_limiter import rate_limiter
from .profiler import resource_checkpoint, _write_json_atomic
from .request_policy import CooldownDeferred

logger = logging.getLogger(__name__)

# Kích thước chunk: 512 KiB.
CHUNK_SIZE: int = 512 * 1024

# Nhịp full-text; metadata có cấu hình riêng.
DEFAULT_RATE_LIMIT_SEC: float = 3.0
ARXIV_COOLDOWN_FLOOR_SEC: float = 15.0
RESUME_SEGMENTS = (16 * 1024 * 1024, 32 * 1024 * 1024, 64 * 1024 * 1024)
_SOURCE_TRANSFER_LOCK = threading.RLock()

ALLOWED_SOURCE_ENDPOINTS: frozenset[str] = frozenset({"src", "e-print"})
DEFAULT_SOURCE_ENDPOINT: str = "src"
SOURCE_ENDPOINT: str = DEFAULT_SOURCE_ENDPOINT
HEAVY_ARCHIVE_BYTES: int = 20 * 1024 * 1024
HEAVY_INTERRUPTIONS_LIMIT: int = 1


def validate_source_endpoint(endpoint: str) -> str:
    """Xác thực source endpoint trong allowlist {'src', 'e-print'}."""
    if not isinstance(endpoint, str) or endpoint not in ALLOWED_SOURCE_ENDPOINTS:
        raise ValueError(
            f"Source endpoint không hợp lệ: {endpoint!r}. Phải là một trong {sorted(ALLOWED_SOURCE_ENDPOINTS)}"
        )
    return endpoint


DEFAULT_USER_AGENT: str = (
    "arxiv-harvester/0.1.0 (Course Project; mailto:24120282@student.hcmus.edu.vn)"
)

# Giữ .bbl làm nguồn bibliography bổ trợ theo QA.
ALLOWLIST_EXTENSIONS: set[str] = {
    ".tex",
    ".bib",
    ".bbl",
}

# Hậu kiểm tra tệp ngoài allowlist.
KEEP_EXTENSIONS: set[str] = {
    ".tex",
    ".bib",
    ".bbl",
    ".sty",
    ".cls",
    ".bst",
    ".txt",
}

# Phần mở rộng ảnh và tệp nhị phân.
IMAGE_AND_BINARY_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
    ".svg", ".eps", ".ps", ".pdf", ".webp", ".ico", ".ai",
    ".pyc", ".pyd", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".tgz",
    ".npy", ".npz", ".pkl", ".pickle", ".h5", ".hdf5", ".pt", ".pth", ".onnx",
    ".parquet", ".feather",
}

NETWORK_EXCEPTIONS = (
    requests.RequestException,
    urllib3.exceptions.HTTPError,
    http.client.HTTPException,
    OSError,
)

# Mã trả về khi chunk đầu là PDF.
_STATUS_EARLY_PDF = 299


class _PDFSource(Exception):
    pass

_ARTICLE_LOCKS_GUARD = threading.Lock()
_ARTICLE_LOCKS: dict[str, threading.RLock] = {}
_DEFAULT_SESSION_LOCK = threading.Lock()
_DEFAULT_SESSION: requests.Session | None = None


def _create_configured_session() -> requests.Session:
    """Tạo Session chuẩn hóa header, tắt nén chồng lớp HTTP để tránh IncompleteRead."""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    })
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


def _get_shared_session() -> requests.Session:
    """Lấy HTTP session dùng chung."""
    global _DEFAULT_SESSION
    with _DEFAULT_SESSION_LOCK:
        if _DEFAULT_SESSION is None:
            _DEFAULT_SESSION = _create_configured_session()
        return _DEFAULT_SESSION


def _get_article_lock(arxiv_id: str) -> threading.RLock:
    """Khóa theo ID để tránh hai lần tải ghi đè nhau."""
    with _ARTICLE_LOCKS_GUARD:
        lock = _ARTICLE_LOCKS.get(arxiv_id)
        if lock is None:
            lock = threading.RLock()
            _ARTICLE_LOCKS[arxiv_id] = lock
        return lock


def reset_rate_limiter() -> None:
    """Đặt lại rate limiter cho test."""
    pass


def get_dir_size_bytes(path: str | Path) -> int:
    """Tổng byte của các tệp thường trong thư mục."""
    if path is None:
        raise TypeError("Đường dẫn không được là None")
    if not isinstance(path, (str, Path, os.PathLike)):
        raise TypeError(f"Đường dẫn phải là str hoặc Path, nhận được: {type(path).__name__}")
    if isinstance(path, str) and not path.strip():
        raise FileNotFoundError("Đường dẫn không được để trống")

    if not os.path.exists(path):
        raise FileNotFoundError(f"Thư mục không tồn tại: {path}")
    if not os.path.isdir(path):
        raise NotADirectoryError(f"Đường dẫn không phải là thư mục: {path}")

    root_path = Path(path)

    def _scan_dir(current_dir: Path) -> int:
        total = 0
        with os.scandir(current_dir) as it:
            for entry in it:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    total += _scan_dir(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
        return total

    return _scan_dir(root_path)


def prune_images_and_binaries(path: str | Path) -> None:
    """Xóa các tệp ngoài allowlist sau giải nén."""
    if path is None:
        raise TypeError("Đường dẫn không được là None")
    if not isinstance(path, (str, Path, os.PathLike)):
        raise TypeError(f"Đường dẫn phải là str hoặc Path, nhận được: {type(path).__name__}")
    if isinstance(path, str) and not path.strip():
        raise FileNotFoundError("Đường dẫn không được để trống")

    if not os.path.exists(path):
        raise FileNotFoundError(f"Thư mục không tồn tại: {path}")
    if not os.path.isdir(path):
        raise NotADirectoryError(f"Đường dẫn không phải là thư mục: {path}")

    root = Path(path).resolve()
    for current_dir, dirs, files in os.walk(root, topdown=False, followlinks=False):
        current_path = Path(current_dir)
        for name in files:
            file_path = current_path / name
            if file_path.is_symlink():
                file_path.unlink(missing_ok=True)
                continue
            ext = file_path.suffix.lower()
            if ext in IMAGE_AND_BINARY_EXTENSIONS or ext not in ALLOWLIST_EXTENSIONS:
                file_path.unlink(missing_ok=True)

        for name in dirs:
            dir_path = current_path / name
            if dir_path.is_symlink():
                dir_path.unlink(missing_ok=True)
            elif not any(dir_path.iterdir()):
                dir_path.rmdir()


def _safe_extract_tar(
    tar: tarfile.TarFile,
    dest_dir: Path,
    max_total_bytes: int = 500 * 1024 * 1024,
) -> tuple[int, int]:
    """Giải nén nguồn và bibliography; trả về byte gốc và byte được giữ."""
    root = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    size_before_bytes = 0
    size_after_bytes = 0

    members_iter = iter(tar.next, None) if (isinstance(tar, tarfile.TarFile) or hasattr(tar, "next")) else tar.getmembers()
    for member in members_iter:
        # Kiểm tra an toàn đường dẫn
        name = member.name.replace("\\", "/")
        parts = name.split("/")
        if not name or name.startswith("/") or any(part == ".." for part in parts):
            raise ValueError(f"Đường dẫn không an toàn trong archive: {member.name!r}")
        if len(name) >= 2 and name[1] == ":":
            raise ValueError(f"Đường dẫn có drive không hợp lệ: {member.name!r}")

        relative_parts = [part for part in parts if part not in ("", ".")]
        target = (dest_dir / Path(*relative_parts)).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Thành viên thoát khỏi thư mục đích: {member.name!r}")

        normalized = target.relative_to(root).as_posix()
        if normalized in seen and not member.isdir():
            raise ValueError(f"Thành viên bị trùng trong archive: {member.name!r}")
        if normalized in seen and member.isdir():
            continue
        seen.add(normalized)

        if not (member.isdir() or member.isfile()):
            continue
        if member.size < 0:
            raise ValueError(f"Kích thước thành viên không hợp lệ: {member.name!r}")

        if member.isfile():
            size_before_bytes += member.size
            if size_before_bytes > max_total_bytes:
                raise ValueError(f"Dung lượng giải nén vượt giới hạn {max_total_bytes} byte")

            ext = Path(member.name).suffix.lower()
            # Không giải nén ảnh hoặc tệp thực thi.
            if ext not in ALLOWLIST_EXTENSIONS:
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                raise tarfile.ExtractError(f"Không đọc được thành viên: {member.name!r}")

            written = 0
            with source, target.open("wb") as output:
                while True:
                    chunk = source.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > member.size or written > max_total_bytes:
                        raise ValueError(f"Kích thước thực tế vượt giới hạn: {member.name!r}")
                    output.write(chunk)

            if written != member.size:
                raise tarfile.ExtractError(f"Dữ liệu không đầy đủ trong thành viên: {member.name!r}")
            size_after_bytes += written

    return size_before_bytes, size_after_bytes


def _extract_single_gz(
    archive_path: Path,
    dest_dir: Path,
    safe_name: str,
    max_output_bytes: int = 500 * 1024 * 1024,
) -> tuple[int, int]:
    """Giải nén tệp gzip đơn lẻ (.gz) thành file .tex nguồn."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_tex = dest_dir / f"{safe_name}.tex"
    written = 0

    with gzip.open(archive_path, "rb") as gz_in, target_tex.open("wb") as out_f:
        while True:
            chunk = gz_in.read(CHUNK_SIZE)
            if not chunk:
                break
            if written == 0 and chunk.lstrip().startswith(b"%PDF-"):
                raise _PDFSource("gzip contains PDF")
            if written == 0 and not any(marker in chunk for marker in (b"\\documentclass", b"\\begin", b"\\input", b"\\section", b"\\def", b"\\documentstyle")):
                raise ValueError("Gzip không chứa nguồn TeX nhận diện được")
            written += len(chunk)
            if written > max_output_bytes:
                raise ValueError(f"Gzip giải nén vượt giới hạn {max_output_bytes} byte")
            out_f.write(chunk)

    return written, written


def _retry_after_seconds(response: requests.Response | None) -> float | None:
    """Đọc Retry-After dạng số giây hoặc HTTP-date."""
    if response is None:
        return None
    value = response.headers.get("Retry-After")
    if not value:
        return None

    try:
        seconds = float(value.strip())
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _response_chunks(response, chunk_size: int):
    raw = getattr(response, "raw", None)
    if raw is not None and callable(getattr(raw, "read1", None)):
        while chunk := raw.read1(chunk_size, decode_content=False):
            yield chunk
    elif raw is not None and hasattr(raw, "stream"):
        yield from raw.stream(chunk_size, decode_content=False)
    else:
        yield from response.iter_content(chunk_size=chunk_size)


def _download_stream(
    url: str,
    dest_path: Path,
    session: requests.Session,
    max_retries: int = 4,
    chunk_size: int = CHUNK_SIZE,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
    max_download_bytes: int = 250 * 1024 * 1024,
    read_timeout_sec: float = 180.0,
    diagnostics: dict | None = None,
    max_elapsed_sec: float = 180.0,
    open_ended_range: bool = False,
    source_endpoint: str = DEFAULT_SOURCE_ENDPOINT,
    allow_defer_heavy: bool = False,
) -> int:
    """Tải theo luồng từ export.arxiv.org/{endpoint}/{id} với rate-limiting tập trung."""
    validate_source_endpoint(source_endpoint)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != "export.arxiv.org":
        raise ValueError(f"Host must be export.arxiv.org, got: {parsed.netloc}")

    partial_path = dest_path.with_name(dest_path.name + ".part")
    details = diagnostics if diagnostics is not None else {}
    details.update(source_url=url, attempts=0, deferred_heavy=False)
    started = time.monotonic()
    deadline = started + max_elapsed_sec
    attempt = 1
    segment_index = 0
    known_total_size = details.get("total_bytes")
    heavy_interruptions = 0

    while attempt <= max_retries:
        try:
            rate_limiter.wait("arxiv", interval=max(1.0, rate_limit_sec))
        except CooldownDeferred as error:
            details.update(error_message=str(error), rate_limited=True, retry_after_sec=error.retry_after)
            return 0
        request_headers = {"Accept-Encoding": "identity"}

        offset = partial_path.stat().st_size if partial_path.exists() else 0
        if offset > 0:
            if open_ended_range or RESUME_SEGMENTS is None:
                request_headers["Range"] = f"bytes={offset}-"
            else:
                request_headers["Range"] = f"bytes={offset}-{offset + RESUME_SEGMENTS[segment_index] - 1}"

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Hết ngân sách thời gian tải; giữ file .part để resume")
            details["attempts"] = attempt
            details["requests"] = details.get("requests", 0) + 1
            request_started = time.monotonic()
            retry_delay = None
            clean_completion = False
            try:
                with session.get(
                    url,
                    stream=True,
                    timeout=(min(15.0, remaining), min(read_timeout_sec, remaining)),
                    headers=request_headers,
                ) as response:
                    details["http_status"] = response.status_code
                    if response.status_code == 429:
                        delay = rate_limiter.policy.limited("arxiv", response, floor=ARXIV_COOLDOWN_FLOOR_SEC)
                        details.update(error_message="HTTP 429; tạm dừng tải và giữ partial", rate_limited=True,
                                       retry_after_sec=delay, next_retry_at=rate_limiter.policy.snapshot("arxiv")["next_retry_at"])
                        return 429
                    if response.status_code == 404:
                        rate_limiter.policy.succeeded("arxiv")
                        partial_path.unlink(missing_ok=True)
                        clean_completion = True
                        return 404

                    if response.status_code == 416:
                        partial_path.unlink(missing_ok=True)
                        offset = 0
                        segment_index = 0
                        attempt += 1
                        continue

                    if response.status_code in (500, 502, 503, 504):
                        segment_index = max(0, segment_index - 1)
                        retry_sec = _retry_after_seconds(response)
                        delay = retry_sec if retry_sec is not None else (attempt * 5.0)
                        details["error_message"] = f"HTTP {response.status_code} khi tải nguồn"
                        rate_limiter.defer("arxiv", delay)
                        if attempt == max_retries or delay >= deadline - time.monotonic():
                            logger.warning("Nguồn %s: HTTP %d, hết %d lượt; giữ để retry", url, response.status_code, attempt)
                            return response.status_code
                        logger.warning("Nguồn %s: HTTP %d, thử %d/%d, chờ %.1fs", url, response.status_code, attempt, max_retries, delay)
                        retry_delay = delay
                        attempt += 1

                    if retry_delay is None:
                        append_mode = offset > 0 and response.status_code == 206
                        if response.status_code not in (200, 206):
                            response.raise_for_status()

                        rate_limiter.policy.succeeded("arxiv")

                        ct = response.headers.get("Content-Type", "").lower()
                        if "application/pdf" in ct:
                            partial_path.unlink(missing_ok=True)
                            clean_completion = True
                            return _STATUS_EARLY_PDF

                        if response.status_code == 200:
                            cl = response.headers.get("Content-Length")
                            if cl is not None:
                                try:
                                    known_total_size = int(cl)
                                    details["total_bytes"] = known_total_size
                                except (ValueError, TypeError):
                                    pass

                        content_range = None
                        total_size = None
                        if response.status_code == 206:
                            content_range = re.fullmatch(r"bytes (\d+)-(\d+)/(?:\*|(\d+))", response.headers.get("Content-Range", ""))
                            if (not content_range or int(content_range[1]) != offset
                                    or not offset <= int(content_range[2])):
                                raise ValueError("Source Content-Range does not match the requested resume offset")
                            total_size = int(content_range[3]) if content_range[3] else None
                            if total_size is not None and int(content_range[2]) >= total_size:
                                raise ValueError("Source Content-Range does not match the requested resume offset")
                            if total_size is not None:
                                known_total_size = total_size
                                details["total_bytes"] = known_total_size

                        mode = "ab" if append_mode else "wb"
                        downloaded = offset if append_mode else 0

                        stream_iter = _response_chunks(response, chunk_size)
                        expected_bytes = (total_size if (response.status_code == 206 and total_size is not None) else
                                          int(response.headers["Content-Length"]) if response.headers.get("Content-Length") is not None else None)

                        next_progress = time.monotonic() + 10
                        early_pdf = False
                        with partial_path.open(mode) as f_out:
                            for chunk in stream_iter:
                                if not chunk:
                                    continue
                                # Phát hiện sớm PDF-only
                                if downloaded == 0 and (chunk.startswith(b"%PDF-") or b"%PDF-" in chunk[:16]):
                                    early_pdf = True
                                    break

                                downloaded += len(chunk)
                                if downloaded > max_download_bytes:
                                    raise ValueError(f"Dung lượng tải vượt quá giới hạn {max_download_bytes} byte")
                                f_out.write(chunk)
                                details["bytes_downloaded"] = downloaded
                                if time.monotonic() >= next_progress:
                                    logger.info("Đang tải %s: %.1f MiB", url, downloaded / 1024**2)
                                    next_progress = time.monotonic() + 10
                                if time.monotonic() >= deadline and downloaded != expected_bytes:
                                    raise TimeoutError("Hết ngân sách thời gian tải; giữ file .part để resume")

                        if early_pdf:
                            partial_path.unlink(missing_ok=True)
                            clean_completion = True
                            return _STATUS_EARLY_PDF

                        if response.status_code == 206 and content_range and downloaded != int(content_range[2]) + 1:
                            raise requests.exceptions.ChunkedEncodingError("Source range ended before the advertised segment")
                        length = response.headers.get("Content-Length")
                        received = downloaded - (offset if append_mode else 0)
                        if length is not None and received != int(length):
                            raise requests.exceptions.ChunkedEncodingError("Source body does not match Content-Length")

                        if response.status_code == 206 and total_size is not None and downloaded < total_size:
                            if time.monotonic() - request_started <= 10:
                                segment_index = min(len(RESUME_SEGMENTS) - 1, segment_index + 1) if RESUME_SEGMENTS else 0
                            else:
                                segment_index = max(0, segment_index - 1)
                            rate_limiter.policy.succeeded("arxiv")
                            continue

                        if partial_path.exists():
                            partial_path.replace(dest_path)
                        rate_limiter.policy.succeeded("arxiv")
                        details.update(bytes_downloaded=downloaded, error_message=None)
                        if downloaded >= 25 * 1024 * 1024 or details.get("requests", 0) > 1:
                            if hasattr(rate_limiter, "mark_heavy_completed"):
                                rate_limiter.mark_heavy_completed("arxiv", padding_sec=1.5)
                            else:
                                rate_limiter._last_called["arxiv"] = time.monotonic() + 1.5
                        clean_completion = True
                        return 200
            finally:
                if not clean_completion:
                    rate_limiter.mark_completed("arxiv")

            if retry_delay is not None:
                time.sleep(retry_delay)
                continue

        except Exception as exc:
            segment_index = max(0, segment_index - 1)
            details["error_message"] = f"{type(exc).__name__}: {exc}"
            current_size = partial_path.stat().st_size if partial_path.exists() else 0
            bytes_gained = current_size - offset
            is_net_exc = isinstance(exc, NETWORK_EXCEPTIONS)
            if is_net_exc:
                heavy_interruptions += 1
                details["heavy_interruptions"] = heavy_interruptions

            # Rule B: Defer heavy, repeatedly-interrupted versions (>= 30 MiB, >= 2 interruptions)
            # Takes priority over forward progress to prevent a 30-45 MiB archive from monopolizing connection
            if (
                allow_defer_heavy
                and is_net_exc
                and (known_total_size or 0) >= HEAVY_ARCHIVE_BYTES
                and heavy_interruptions >= HEAVY_INTERRUPTIONS_LIMIT
            ):
                msg = (
                    f"Nguồn nặng ({(known_total_size or 0) / (1024*1024):.1f} MiB >= {HEAVY_ARCHIVE_BYTES / (1024*1024):.0f} MiB) "
                    f"bị gián đoạn mạng {heavy_interruptions} lần (đã tải {current_size / (1024*1024):.1f} MiB); "
                    f"hoãn về đợt sweep cuối để nhường kết nối"
                )
                logger.warning("Nguồn %s: %s", url, msg)
                details.update(
                    deferred_heavy=True,
                    error_message=msg,
                    bytes_downloaded=current_size,
                    heavy_interruptions=heavy_interruptions,
                )
                return 0

            if time.monotonic() >= deadline:
                logger.warning("Nguồn %s: %s; dừng lượt tải, lần sau resume", url, details["error_message"])
                if allow_defer_heavy and is_net_exc and current_size >= 512 * 1024:
                    details.update(deferred_heavy=True, bytes_downloaded=current_size)
                elif not is_net_exc:
                    partial_path.unlink(missing_ok=True)
                return 0

            # Rule A: Forward-progress resume (>= 512 KiB gained does not burn retry budget or penalty sleep)
            if is_net_exc and bytes_gained >= 512 * 1024 and details.get("requests", 0) < 64:
                logger.info(
                    "Nguồn %s: Tiến triển %.1f MiB (+%.1f KiB) trước khi gián đoạn mạng (%s); tiếp tục resume",
                    url, current_size / 1024**2, bytes_gained / 1024, type(exc).__name__
                )
                continue

            if attempt < max_retries and (attempt + 1) * 3.0 >= deadline - time.monotonic():
                logger.warning("Nguồn %s: %s; dừng lượt tải, lần sau resume", url, details["error_message"])
                if allow_defer_heavy and is_net_exc and current_size >= 512 * 1024:
                    details.update(deferred_heavy=True, bytes_downloaded=current_size)
                elif not is_net_exc:
                    partial_path.unlink(missing_ok=True)
                return 0
            if attempt < max_retries:
                logger.warning("Nguồn %s: %s, thử %d/%d; giữ phần đã tải", url, details["error_message"], attempt, max_retries)
                time.sleep((attempt + 1) * 3.0)
                attempt += 1
            else:
                if not is_net_exc:
                    partial_path.unlink(missing_ok=True)
                logger.warning("Thất bại khi tải %s sau %d lần thử: %s", url, max_retries, exc)
                return 0

    return 0


def _split_version_id(arxiv_id: str) -> tuple[str, str, str]:
    """Tách (base_id, version_tag, versioned_id); mặc định version là v1."""
    clean_val = arxiv_id.strip()
    match = re.search(r"^(.*?)(v\d+)?$", clean_val)
    if not match:
        raise ValueError(f"Mã arXiv không hợp lệ: {arxiv_id!r}")
    base_id = match.group(1)
    ver = match.group(2) or "v1"
    return base_id, ver, f"{base_id}{ver}"


def _validate_arxiv_id(arxiv_id: str) -> tuple[str, str]:
    """Xác thực mã arXiv và trả về (mã gốc, tên an toàn thay thế dấu gạch chéo)."""
    if not isinstance(arxiv_id, str):
        raise TypeError("arxiv_id phải là chuỗi")
    value = arxiv_id.strip()
    modern = re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", value)
    legacy = re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]*(?:\.[A-Za-z]{2})?/\d{7}(?:v\d+)?", value)
    if not value or not (modern or legacy):
        raise ValueError(f"Mã arXiv không hợp lệ: {arxiv_id!r}")
    return value, value.replace("/", "_")


def extract_and_clean_archive(
    archive_path: str | Path,
    version_extract_dir: str | Path,
    base_id: str | None = None,
    ver: str | None = None,
    keep_archives: bool = False,
    remove_archive: bool | None = None,
    unzipped_dir: str | Path | None = None,
    start_time: float | None = None,
) -> dict:
    """Giải nén và dọn dẹp archive nguồn bài báo arXiv sang thư mục version."""
    archive_path = Path(archive_path)
    final_version_dir = Path(version_extract_dir)
    ver = ver or final_version_dir.name
    base_id = base_id or final_version_dir.parent.name
    safe_base_id = base_id.replace("/", "_")
    versioned_id = f"{base_id}{ver}"
    unzipped_path = Path(unzipped_dir) if unzipped_dir is not None else final_version_dir.parent.parent

    should_remove = (not keep_archives) if remove_archive is None else remove_archive
    t0 = start_time if start_time is not None else time.perf_counter()

    if not archive_path.exists():
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": round(time.perf_counter() - t0, 3),
            "source_dir": str(final_version_dir),
            "error_message": "Archive path does not exist",
        }

    # Đọc byte đầu nhận diện tệp nén
    try:
        with open(archive_path, "rb") as f:
            header_bytes = f.read(1024)
    except OSError:
        if should_remove and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": round(time.perf_counter() - t0, 3),
            "source_dir": str(final_version_dir),
        }

    if header_bytes.startswith(b"%PDF-") or b"%PDF-" in header_bytes[:16]:
        final_version_dir.mkdir(parents=True, exist_ok=True)
        if should_remove and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "pdf_only",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": round(time.perf_counter() - t0, 3),
            "source_dir": str(final_version_dir),
        }

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{safe_base_id}_{ver}.staging-", dir=unzipped_path))
    size_before_bytes = 0
    size_after_bytes = 0
    extracted_ok = False

    try:
        try:
            with tarfile.open(archive_path, "r:*") as tar:
                size_before_bytes, size_after_bytes = _safe_extract_tar(tar, staging_dir)
            extracted_ok = True
        except (tarfile.ReadError, tarfile.CompressionError):
            extracted_ok = False

        if not extracted_ok:
            if header_bytes.startswith(b"\x1f\x8b"):
                size_before_bytes, size_after_bytes = _extract_single_gz(archive_path, staging_dir, f"{safe_base_id}{ver}")
                extracted_ok = True
            else:
                with archive_path.open("rb") as sf:
                    sample = sf.read(64 * 1024)
                sample_text = sample.decode("utf-8", errors="ignore")
                if any(marker in sample_text for marker in (r"\documentclass", r"\begin{document}", r"\input", r"\section")):
                    target_tex = staging_dir / f"{safe_base_id}{ver}.tex"
                    shutil.copyfile(archive_path, target_tex)
                    size_before_bytes = archive_path.stat().st_size
                    size_after_bytes = size_before_bytes
                    extracted_ok = True
    except _PDFSource:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if should_remove and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        final_version_dir.mkdir(parents=True, exist_ok=True)
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "pdf_only",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": round(time.perf_counter() - t0, 3),
            "source_dir": str(final_version_dir),
        }
    except Exception as exc:
        logger.warning("Lỗi khi giải nén bài báo %s: %s", versioned_id, exc)
        extracted_ok = False

    if not extracted_ok:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if should_remove and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": round(time.perf_counter() - t0, 3),
            "source_dir": str(final_version_dir),
        }

    # Loại tệp ngoài allowlist sau giải nén.
    prune_images_and_binaries(staging_dir)
    size_after_bytes = get_dir_size_bytes(staging_dir) if staging_dir.exists() else 0

    has_tex = False
    has_bib = False
    if staging_dir.exists():
        for root_dir, _, filenames in os.walk(staging_dir):
            for name in filenames:
                ext = Path(name).suffix.lower()
                if ext == ".tex":
                    has_tex = True
                elif ext == ".bib":
                    has_bib = True
                if has_tex and has_bib:
                    break
            if has_tex and has_bib:
                break

    if not has_tex:
        status = "no_latex"
    else:
        status = "success"

    # Chỉ thay nguồn cũ sau khi staging hợp lệ.
    if not final_version_dir.resolve().is_relative_to(unzipped_path.resolve()):
        raise ValueError("Thư mục version thoát ngoài corpus")
    previous_tex = False
    if final_version_dir.exists():
        for root_dir, _, filenames in os.walk(final_version_dir):
            if any(name.lower().endswith(".tex") for name in filenames):
                previous_tex = True
                break
    if status != "success" and previous_tex:
        shutil.rmtree(staging_dir)
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "error",
            "size_before_bytes": size_before_bytes,
            "size_after_bytes": get_dir_size_bytes(final_version_dir),
            "elapsed_sec": round(time.perf_counter() - t0, 3),
            "source_dir": str(final_version_dir),
            "error_message": "New archive has no TeX; preserved previous source",
        }
    final_version_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = final_version_dir.with_name(f".{ver}.previous-{uuid.uuid4().hex}")
    if final_version_dir.exists():
        os.replace(final_version_dir, backup_dir)
    try:
        os.replace(staging_dir, final_version_dir)
    except BaseException:
        if backup_dir.exists() and not final_version_dir.exists():
            os.replace(backup_dir, final_version_dir)
        raise
    if backup_dir.exists():
        if not backup_dir.resolve().is_relative_to(unzipped_path.resolve()) or backup_dir.is_symlink():
            raise ValueError("Backup source path escapes corpus")
        try:
            shutil.rmtree(backup_dir)
        except OSError as error:
            logger.warning("Giữ backup nguồn %s vì chưa dọn được: %s", backup_dir, error)

    if should_remove and archive_path.exists():
        archive_path.unlink(missing_ok=True)

    elapsed_sec = round(time.perf_counter() - t0, 3)

    return {
        "arxiv_id": base_id,
        "version_id": versioned_id,
        "status": status,
        "size_before_bytes": size_before_bytes,
        "size_after_bytes": size_after_bytes,
        "elapsed_sec": elapsed_sec,
        "source_dir": str(final_version_dir),
    }


def _write_version_manifest_and_scan_bbl(result: dict, sources_dir: str | Path, valid_endpoint: str) -> dict:
    directory = Path(result["source_dir"])
    bbl_files = []
    has_dir_tex = False
    if directory.is_dir():
        for root_dir, _, filenames in os.walk(directory):
            root_path = Path(root_dir)
            for f in filenames:
                lower = f.lower()
                if lower.endswith(".bbl"):
                    file_p = root_path / f
                    if not file_p.is_symlink():
                        bbl_files.append(file_p.relative_to(directory).as_posix())
                elif lower.endswith(".tex"):
                    has_dir_tex = True
    result["bbl_files"] = sorted(bbl_files)
    if result.get("status") == "pdf_only" and has_dir_tex:
        result.update(status="error", error_message="PDF response conflicts with existing TeX; previous source preserved")
    manifest = Path(sources_dir).parent / "manifests" / (result["version_id"].replace("/", "_") + ".json")
    manifest_url = result.get("source_url") or f"https://export.arxiv.org/{valid_endpoint}/{result['version_id']}"
    _write_json_atomic(str(manifest), {**result, "source_url": manifest_url,
                                      "evidence": "pdf_header" if result.get("status") == "pdf_only" else
                                                  "tex_extracted" if result.get("status") == "success" else
                                                  "archive_without_tex" if result.get("status") == "no_latex" else
                                                  "http_404" if result.get("status") == "not_found" else "request_or_extraction_error"})
    return result


def _finalize_version_extraction(
    archive_path: Path,
    final_version_dir: Path,
    base_id: str,
    ver: str,
    remove_archive: bool,
    unzipped_path: Path,
    start_time: float,
    url: str,
    valid_endpoint: str,
    sources_dir: str | Path,
    validated_id: str,
) -> dict:
    with _get_article_lock(validated_id):
        res = extract_and_clean_archive(
            archive_path=archive_path,
            version_extract_dir=final_version_dir,
            base_id=base_id,
            ver=ver,
            remove_archive=remove_archive,
            unzipped_dir=unzipped_path,
            start_time=start_time,
        )
        res.update(source_url=url, deferred_heavy=False)
        return _write_version_manifest_and_scan_bbl(res, sources_dir, valid_endpoint)


def _download_and_clean_source_impl(
    arxiv_id: str,
    sources_dir: str,
    unzipped_dir: str,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
    remove_archive: bool = True,
    session: requests.Session | None = None,
    max_attempts: int = 4,
    read_timeout_sec: float = 180.0,
    max_elapsed_sec: float = 180.0,
    open_ended_range: bool = False,
    executor: concurrent.futures.Executor | None = None,
    source_endpoint: str = DEFAULT_SOURCE_ENDPOINT,
    allow_defer_heavy: bool = True,
    async_extract: bool = False,
) -> dict:
    """Tải và giải nén mã nguồn của một phiên bản bài báo arXiv từ export.arxiv.org/{endpoint}/."""
    raw_id, _ = _validate_arxiv_id(arxiv_id)
    base_id, ver, versioned_id = _split_version_id(raw_id)
    safe_base_id = base_id.replace("/", "_")
    valid_endpoint = validate_source_endpoint(source_endpoint)

    sources_path = Path(sources_dir)
    unzipped_path = Path(unzipped_dir)
    sources_path.mkdir(parents=True, exist_ok=True)
    unzipped_path.mkdir(parents=True, exist_ok=True)

    # Mỗi version có thư mục riêng: unzipped/<base_id>/<version>/.
    archive_path = sources_path / f"{safe_base_id}{ver}.tar.gz"
    final_version_dir = unzipped_path / safe_base_id / ver

    req_session = session if session is not None else _get_shared_session()
    start_time = time.perf_counter()

    # Tải đúng version qua /{endpoint}/{versioned_id}.
    url = f"https://export.arxiv.org/{valid_endpoint}/{versioned_id}"
    download_details = {}
    with _SOURCE_TRANSFER_LOCK:
        http_status = _download_stream(
            url,
            archive_path,
            session=req_session,
            chunk_size=CHUNK_SIZE,
            rate_limit_sec=float(rate_limit_sec),
            max_retries=max_attempts,
            read_timeout_sec=read_timeout_sec,
            diagnostics=download_details,
            max_elapsed_sec=max_elapsed_sec,
            open_ended_range=open_ended_range,
            source_endpoint=valid_endpoint,
            allow_defer_heavy=allow_defer_heavy,
        )

    elapsed_sec = round(time.perf_counter() - start_time, 3)

    if http_status == 404:
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "not_found",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
            "source_dir": str(final_version_dir),
            "source_url": url,
            "deferred_heavy": False,
        }

    if http_status == _STATUS_EARLY_PDF:
        final_version_dir.mkdir(parents=True, exist_ok=True)
        if remove_archive and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "pdf_only",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
            "source_dir": str(final_version_dir),
            "source_url": url,
            "deferred_heavy": False,
        }

    if http_status != 200 or not archive_path.exists():
        return {
            **download_details,
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
            "source_dir": str(final_version_dir),
            "source_url": url,
            "deferred_heavy": download_details.get("deferred_heavy", False),
        }

    if executor is not None and async_extract:
        future = executor.submit(
            _finalize_version_extraction,
            archive_path=archive_path,
            final_version_dir=final_version_dir,
            base_id=base_id,
            ver=ver,
            remove_archive=remove_archive,
            unzipped_path=unzipped_path,
            start_time=start_time,
            url=url,
            valid_endpoint=valid_endpoint,
            sources_dir=sources_dir,
            validated_id=raw_id,
        )
        return {
            "status": "extracting",
            "_extract_future": future,
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "source_dir": str(final_version_dir),
            "source_url": url,
            "deferred_heavy": False,
        }

    if executor is not None:
        future = executor.submit(
            extract_and_clean_archive,
            archive_path=archive_path,
            version_extract_dir=final_version_dir,
            base_id=base_id,
            ver=ver,
            remove_archive=remove_archive,
            unzipped_dir=unzipped_path,
            start_time=start_time,
        )
        res = future.result()
        res.update(source_url=url, deferred_heavy=False)
        return res

    res = extract_and_clean_archive(
        archive_path=archive_path,
        version_extract_dir=final_version_dir,
        base_id=base_id,
        ver=ver,
        remove_archive=remove_archive,
        unzipped_dir=unzipped_path,
        start_time=start_time,
    )
    res.update(source_url=url, deferred_heavy=False)
    return res


_default_download_and_clean_source_impl = _download_and_clean_source_impl


def download_and_clean_source(
    arxiv_id: str,
    sources_dir: str,
    unzipped_dir: str,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
    remove_archive: bool = True,
    session: requests.Session | None = None,
    max_attempts: int = 4,
    read_timeout_sec: float = 180.0,
    max_elapsed_sec: float = 180.0,
    keep_archives: bool = False,
    open_ended_range: bool = False,
    executor: concurrent.futures.Executor | None = None,
    source_endpoint: str = DEFAULT_SOURCE_ENDPOINT,
    allow_defer_heavy: bool = True,
    async_extract: bool = False,
) -> dict:
    """Tải, giải nén và lọc nguồn của một version arXiv."""
    validated_id, _ = _validate_arxiv_id(arxiv_id)
    valid_endpoint = validate_source_endpoint(source_endpoint)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if not math.isfinite(read_timeout_sec) or read_timeout_sec <= 0:
        raise ValueError("read_timeout_sec must be positive and finite")
    if not math.isfinite(max_elapsed_sec) or max_elapsed_sec <= 0:
        raise ValueError("max_elapsed_sec must be positive and finite")
    if not math.isfinite(rate_limit_sec) or rate_limit_sec < 1:
        raise ValueError("Source rate_limit_sec must be >= 1")
    transfer_lock = (
        _SOURCE_TRANSFER_LOCK
        if _download_and_clean_source_impl is not _default_download_and_clean_source_impl
        else contextlib.nullcontext()
    )
    should_remove = (not keep_archives) if remove_archive is None else remove_archive
    with transfer_lock, _get_article_lock(validated_id):
        result = _download_and_clean_source_impl(
            arxiv_id=arxiv_id,
            sources_dir=sources_dir,
            unzipped_dir=unzipped_dir,
            rate_limit_sec=rate_limit_sec,
            remove_archive=should_remove,
            session=session,
            max_attempts=max_attempts,
            read_timeout_sec=read_timeout_sec,
            max_elapsed_sec=max_elapsed_sec,
            open_ended_range=open_ended_range,
            executor=executor,
            source_endpoint=valid_endpoint,
            allow_defer_heavy=allow_defer_heavy,
            async_extract=async_extract,
        )
        if result.get("status") == "extracting":
            return result
        return _write_version_manifest_and_scan_bbl(result, sources_dir, valid_endpoint)


download_and_extract_source = download_and_clean_source


if __name__ == "__main__":
    print("Source downloader test")
    test_id = "2412.18848v1"
    sources_test = "data/raw/sources_test"
    unzipped_test = "data/raw/unzipped_test"

    print(f"Downloading source: {test_id}")
    res = download_and_clean_source(
        arxiv_id=test_id,
        sources_dir=sources_test,
        unzipped_dir=unzipped_test,
        rate_limit_sec=3.0,
        remove_archive=True,
    )

    print(f"Download result:")
    print(f"  - Base ID: {res['arxiv_id']}")
    print(f"  - Version ID: {res['version_id']}")
    print(f"  - Status: {res['status']}")
    print(f"  - Original size (uncompressed): {res['size_before_bytes']} bytes")
    print(f"  - Cleaned source size: {res['size_after_bytes']} bytes")
    print(f"  - Saved directory: {res['source_dir']}")
    print(f"  - Elapsed: {res['elapsed_sec']}s")

    # Clean up test directories
    shutil.rmtree(sources_test, ignore_errors=True)
    shutil.rmtree(unzipped_test, ignore_errors=True)
    print("Test completed and cleaned up.")
