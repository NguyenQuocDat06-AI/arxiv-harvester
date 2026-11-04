"""Tải và dọn mã nguồn. Phụ trách: Nguyễn Đình Tuấn (24120237)."""

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

# Kích thước chunk: 64 KiB.
CHUNK_SIZE: int = 64 * 1024

# Nhịp full-text; metadata có cấu hình riêng.
DEFAULT_RATE_LIMIT_SEC: float = 3.0
RESUME_SEGMENTS = (1024 * 1024, 4 * 1024 * 1024, 8 * 1024 * 1024)
_SOURCE_TRANSFER_LOCK = threading.RLock()


DEFAULT_USER_AGENT: str = (
    "arxiv-harvester/0.1.0 (Course Project; mailto:24120282@student.hcmus.edu.vn)"
)

# Chỉ giữ nguồn TeX và BibTeX.
ALLOWLIST_EXTENSIONS: set[str] = {
    ".tex",
    ".bib",
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
    """Giải nén .tex/.bib; trả về tổng byte gốc và byte được giữ."""
    root = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    size_before_bytes = 0
    size_after_bytes = 0

    for member in tar.getmembers():
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
            # Chỉ giải nén .tex và .bib.
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
) -> int:
    """Tải theo luồng từ export.arxiv.org/src/{id} với rate-limiting tập trung."""
    partial_path = dest_path.with_name(dest_path.name + ".part")
    details = diagnostics if diagnostics is not None else {}
    details.update(source_url=url, attempts=0)
    started = time.monotonic()
    deadline = started + max_elapsed_sec
    attempt = 1
    segment_index = 0

    while attempt <= max_retries:
        try:
            rate_limiter.wait("arxiv", interval=max(1.0, rate_limit_sec))
        except CooldownDeferred as error:
            details.update(error_message=str(error), rate_limited=True, retry_after_sec=error.retry_after)
            return 0
        request_headers = {"Accept-Encoding": "identity"}

        offset = partial_path.stat().st_size if partial_path.exists() else 0
        if offset > 0:
            request_headers["Range"] = f"bytes={offset}-{offset + RESUME_SEGMENTS[segment_index] - 1}"

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Hết ngân sách thời gian tải; giữ file .part để resume")
            details["attempts"] = attempt
            details["requests"] = details.get("requests", 0) + 1
            request_started = time.monotonic()
            with session.get(
                url,
                stream=True,
                timeout=(min(15.0, remaining), min(read_timeout_sec, remaining)),
                headers=request_headers,
            ) as response:
                details["http_status"] = response.status_code
                if response.status_code == 429:
                    delay = rate_limiter.policy.limited("arxiv", response)
                    details.update(error_message="HTTP 429; tạm dừng tải và giữ partial", rate_limited=True,
                                   retry_after_sec=delay, next_retry_at=rate_limiter.policy.snapshot("arxiv")["next_retry_at"])
                    return 429
                if response.status_code == 404:
                    partial_path.unlink(missing_ok=True)
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
                    time.sleep(delay)
                    attempt += 1
                    continue

                append_mode = offset > 0 and response.status_code == 206
                if response.status_code not in (200, 206):
                    response.raise_for_status()
                if response.status_code == 206:
                    content_range = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if (not content_range or int(content_range[1]) != offset
                            or not offset <= int(content_range[2]) < int(content_range[3])):
                        raise ValueError("Source Content-Range does not match the requested resume offset")

                mode = "ab" if append_mode else "wb"
                downloaded = offset if append_mode else 0

                stream_iter = _response_chunks(response, chunk_size)
                expected_bytes = (int(content_range[3]) if response.status_code == 206 else
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
                    return _STATUS_EARLY_PDF

                if response.status_code == 206 and downloaded != int(content_range[2]) + 1:
                    raise requests.exceptions.ChunkedEncodingError("Source range ended before the advertised segment")
                length = response.headers.get("Content-Length")
                received = downloaded - (offset if append_mode else 0)
                if length is not None and received != int(length):
                    raise requests.exceptions.ChunkedEncodingError("Source body does not match Content-Length")

                if response.status_code == 206 and downloaded < int(content_range[3]):
                    if time.monotonic() - request_started <= 10:
                        segment_index = min(len(RESUME_SEGMENTS) - 1, segment_index + 1)
                    else:
                        segment_index = max(0, segment_index - 1)
                    rate_limiter.policy.succeeded("arxiv")
                    continue

                if partial_path.exists():
                    partial_path.replace(dest_path)
                rate_limiter.policy.succeeded("arxiv")
                details.update(bytes_downloaded=downloaded, error_message=None)
                return 200

        except Exception as exc:
            segment_index = max(0, segment_index - 1)
            details["error_message"] = f"{type(exc).__name__}: {exc}"
            if time.monotonic() >= deadline or (attempt < max_retries and (attempt + 1) * 3.0 >= deadline - time.monotonic()):
                logger.warning("Nguồn %s: %s; dừng lượt tải, lần sau resume", url, details["error_message"])
                if not isinstance(exc, NETWORK_EXCEPTIONS):
                    partial_path.unlink(missing_ok=True)
                return 0
            if attempt < max_retries:
                logger.warning("Nguồn %s: %s, thử %d/%d; giữ phần đã tải", url, details["error_message"], attempt, max_retries)
                time.sleep((attempt + 1) * 3.0)
                attempt += 1
            else:
                if not isinstance(exc, NETWORK_EXCEPTIONS):
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
) -> dict:
    """Tải và giải nén mã nguồn của một phiên bản bài báo arXiv từ export.arxiv.org/src/."""
    raw_id, _ = _validate_arxiv_id(arxiv_id)
    base_id, ver, versioned_id = _split_version_id(raw_id)
    safe_base_id = base_id.replace("/", "_")

    sources_path = Path(sources_dir)
    unzipped_path = Path(unzipped_dir)
    sources_path.mkdir(parents=True, exist_ok=True)
    unzipped_path.mkdir(parents=True, exist_ok=True)

    # Mỗi version có thư mục riêng: unzipped/<base_id>/<version>/.
    archive_path = sources_path / f"{safe_base_id}{ver}.tar.gz"
    final_version_dir = unzipped_path / safe_base_id / ver

    req_session = session if session is not None else _get_shared_session()
    start_time = time.perf_counter()

    # Tải đúng version qua /src/{versioned_id}.
    url = f"https://export.arxiv.org/src/{versioned_id}"
    download_details = {}
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
    )

    elapsed_sec = round(time.perf_counter() - start_time, 3)
    resource_checkpoint()

    if http_status == 404:
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "not_found",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
            "source_dir": str(final_version_dir),
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
        }

    # Đọc byte đầu nhận diện tệp nén
    try:
        with open(archive_path, "rb") as f:
            header_bytes = f.read(1024)
    except OSError:
        if remove_archive and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
            "source_dir": str(final_version_dir),
        }

    if header_bytes.startswith(b"%PDF-") or b"%PDF-" in header_bytes[:16]:
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
        }

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{safe_base_id}_{ver}.staging-", dir=unzipped_path))
    size_before_bytes = 0
    size_after_bytes = 0
    extracted_ok = False

    try:
        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:*") as tar:
                size_before_bytes, size_after_bytes = _safe_extract_tar(tar, staging_dir)
            extracted_ok = True
        elif header_bytes.startswith(b"\x1f\x8b"):
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
        resource_checkpoint()
        shutil.rmtree(staging_dir, ignore_errors=True)
        if remove_archive:
            archive_path.unlink(missing_ok=True)
        final_version_dir.mkdir(parents=True, exist_ok=True)
        return {"arxiv_id": base_id, "version_id": versioned_id, "status": "pdf_only",
                "size_before_bytes": 0, "size_after_bytes": 0,
                "elapsed_sec": round(time.perf_counter() - start_time, 3), "source_dir": str(final_version_dir)}
    except Exception as exc:
        logger.warning("Lỗi khi giải nén bài báo %s: %s", versioned_id, exc)
        extracted_ok = False

    if not extracted_ok:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if remove_archive and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": base_id,
            "version_id": versioned_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
            "source_dir": str(final_version_dir),
        }

    # Loại tệp ngoài allowlist sau giải nén.
    prune_images_and_binaries(staging_dir)
    size_after_bytes = get_dir_size_bytes(staging_dir) if staging_dir.exists() else 0
    resource_checkpoint()

    has_tex = any(p.is_file() and p.suffix.lower() == ".tex" for p in staging_dir.rglob("*"))
    has_bib = any(p.is_file() and p.suffix.lower() == ".bib" for p in staging_dir.rglob("*"))

    if not has_tex:
        status = "no_latex"
    else:
        status = "success"

    # Chỉ thay nguồn cũ sau khi staging hợp lệ.
    if not final_version_dir.resolve().is_relative_to(unzipped_path.resolve()):
        raise ValueError("Thư mục version thoát ngoài corpus")
    previous_tex = final_version_dir.exists() and any(p.is_file() and p.suffix.lower() == ".tex" for p in final_version_dir.rglob("*"))
    if status != "success" and previous_tex:
        shutil.rmtree(staging_dir)
        return {"arxiv_id": base_id, "version_id": versioned_id, "status": "error",
                "size_before_bytes": size_before_bytes, "size_after_bytes": get_dir_size_bytes(final_version_dir),
                "elapsed_sec": round(time.perf_counter() - start_time, 3), "source_dir": str(final_version_dir),
                "error_message": "New archive has no TeX; preserved previous source"}
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
    resource_checkpoint()
    if backup_dir.exists():
        if not backup_dir.resolve().is_relative_to(unzipped_path.resolve()) or backup_dir.is_symlink():
            raise ValueError("Backup source path escapes corpus")
        try:
            shutil.rmtree(backup_dir)
        except OSError as error:
            logger.warning("Giữ backup nguồn %s vì chưa dọn được: %s", backup_dir, error)

    if remove_archive and archive_path.exists():
        archive_path.unlink(missing_ok=True)

    elapsed_sec = round(time.perf_counter() - start_time, 3)

    return {
        "arxiv_id": base_id,
        "version_id": versioned_id,
        "status": status,
        "size_before_bytes": size_before_bytes,
        "size_after_bytes": size_after_bytes,
        "elapsed_sec": elapsed_sec,
        "source_dir": str(final_version_dir),
    }


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
) -> dict:
    """Tải, giải nén và lọc nguồn của một version arXiv."""
    validated_id, _ = _validate_arxiv_id(arxiv_id)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if not math.isfinite(read_timeout_sec) or read_timeout_sec <= 0:
        raise ValueError("read_timeout_sec must be positive and finite")
    if not math.isfinite(max_elapsed_sec) or max_elapsed_sec <= 0:
        raise ValueError("max_elapsed_sec must be positive and finite")
    if not math.isfinite(rate_limit_sec) or rate_limit_sec < 1:
        raise ValueError("Source rate_limit_sec must be >= 1")
    with _SOURCE_TRANSFER_LOCK, _get_article_lock(validated_id):
        result = _download_and_clean_source_impl(
            arxiv_id=arxiv_id,
            sources_dir=sources_dir,
            unzipped_dir=unzipped_dir,
            rate_limit_sec=rate_limit_sec,
            remove_archive=remove_archive,
            session=session,
            max_attempts=max_attempts,
            read_timeout_sec=read_timeout_sec,
            max_elapsed_sec=max_elapsed_sec,
        )
        if result["status"] == "pdf_only" and any(p.is_file() and p.suffix.lower() == ".tex" for p in Path(result["source_dir"]).rglob("*")):
            result.update(status="error", error_message="PDF response conflicts with existing TeX; previous source preserved")
        manifest = Path(sources_dir).parent / "manifests" / (result["version_id"].replace("/", "_") + ".json")
        _write_json_atomic(str(manifest), {**result, "source_url": f"https://export.arxiv.org/src/{result['version_id']}",
                                          "evidence": "pdf_header" if result["status"] == "pdf_only" else
                                                      "tex_extracted" if result["status"] == "success" else
                                                      "archive_without_tex" if result["status"] == "no_latex" else "request_or_extraction_error"})
        return result


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
    print(f"  - Cleaned size (.tex/.bib): {res['size_after_bytes']} bytes")
    print(f"  - Saved directory: {res['source_dir']}")
    print(f"  - Elapsed: {res['elapsed_sec']}s")

    # Clean up test directories
    shutil.rmtree(sources_test, ignore_errors=True)
    shutil.rmtree(unzipped_test, ignore_errors=True)
    print("Test completed and cleaned up.")
