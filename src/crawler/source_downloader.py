"""Tải và dọn mã nguồn arXiv theo phiên bản. Phụ trách: Nguyễn Đình Tuấn (24120237)."""

from __future__ import annotations

import gzip
import http.client
import logging
import os
import random
import re
import shutil
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import urllib3.exceptions
from requests.adapters import HTTPAdapter

try:
    from src.crawler.rate_limiter import rate_limiter
except ImportError:
    from rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Kích thước chunk tải e-print theo luồng: 64 KB
CHUNK_SIZE: int = 64 * 1024

# Thời gian nghỉ tối thiểu mặc định giữa các request tới arXiv: 3.0 giây
DEFAULT_RATE_LIMIT_SEC: float = 3.0

# User-Agent định danh khi gửi request tới arXiv
DEFAULT_USER_AGENT: str = (
    "arxiv-harvester/0.1.0 (Course Project; mailto:24120282@student.hcmus.edu.vn)"
)

# Chỉ cho phép giải nén các tệp văn bản mã nguồn theo allowlist đề bài
ALLOWLIST_EXTENSIONS: set[str] = {
    ".tex",
    ".bib",
}

# Danh sách mở rộng bổ sung dùng cho hàm hậu kiểm tra (defense-in-depth)
KEEP_EXTENSIONS: set[str] = {
    ".tex",
    ".bib",
    ".bbl",
    ".sty",
    ".cls",
    ".bst",
    ".txt",
}

# Danh sách phần mở rộng hình ảnh, đồ họa và tệp nhị phân cần loại bỏ
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

# Mã nội bộ trả về từ _download_stream khi phát hiện sớm PDF-only ngay từ chunk đầu tiên
_STATUS_EARLY_PDF = 299

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
    """Lấy session dùng chung trong process."""
    global _DEFAULT_SESSION
    with _DEFAULT_SESSION_LOCK:
        if _DEFAULT_SESSION is None:
            _DEFAULT_SESSION = _create_configured_session()
        return _DEFAULT_SESSION


def _get_article_lock(arxiv_id: str) -> threading.RLock:
    """Lấy lock theo bài để hai lần tải cùng ID không ghi đè file của nhau."""
    with _ARTICLE_LOCKS_GUARD:
        lock = _ARTICLE_LOCKS.get(arxiv_id)
        if lock is None:
            lock = threading.RLock()
            _ARTICLE_LOCKS[arxiv_id] = lock
        return lock


def reset_rate_limiter() -> None:
    """Đặt lại rate limiter (tiện ích cho unit test)."""
    pass


def get_dir_size_bytes(path: str | Path) -> int:
    """Đo tổng dung lượng (byte) của các tệp thông thường trong thư mục, bao gồm thư mục con."""
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
    """Hậu kiểm tra loại bỏ tệp nhị phân và ảnh (defense-in-depth)."""
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
    """Giải nén an toàn tarfile với Allowlist trực tiếp (.tex và .bib).
    
    Returns:
        tuple[int, int]: (size_before_bytes, size_after_bytes)
        - size_before_bytes: Tổng dung lượng uncompressed của tất cả các file trong archive.
        - size_after_bytes: Tổng dung lượng các file .tex và .bib được giải nén vào thư mục.
    """
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
            # ÁP DỤNG ALLOWLIST: Chỉ trích xuất file .tex và .bib
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
        return max(0.0, float(value.strip()))
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _download_stream(
    url: str,
    dest_path: Path,
    session: requests.Session,
    max_retries: int = 4,
    chunk_size: int = CHUNK_SIZE,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
    max_download_bytes: int = 250 * 1024 * 1024,
) -> int:
    """Tải theo luồng từ export.arxiv.org/src/{id} với rate-limiting tập trung."""
    partial_path = dest_path.with_name(dest_path.name + ".part")
    attempt = 1

    while attempt <= max_retries:
        rate_limiter.wait("arxiv", interval=rate_limit_sec)
        request_headers = {"Accept-Encoding": "identity"}

        offset = partial_path.stat().st_size if partial_path.exists() else 0
        if offset > 0:
            request_headers["Range"] = f"bytes={offset}-"

        try:
            with session.get(
                url,
                stream=True,
                timeout=(15.0, 180.0),
                headers=request_headers,
            ) as response:
                if response.status_code == 404:
                    partial_path.unlink(missing_ok=True)
                    return 404

                if response.status_code == 416:
                    partial_path.unlink(missing_ok=True)
                    offset = 0
                    attempt += 1
                    continue

                if response.status_code in (429, 503):
                    retry_sec = _retry_after_seconds(response)
                    delay = retry_sec if retry_sec is not None else (attempt * 5.0)
                    time.sleep(delay)
                    attempt += 1
                    continue

                append_mode = offset > 0 and response.status_code == 206
                if response.status_code not in (200, 206):
                    response.raise_for_status()

                mode = "ab" if append_mode else "wb"
                downloaded = offset if append_mode else 0

                raw = getattr(response, "raw", None)
                stream_iter = (
                    raw.stream(max(chunk_size, 256 * 1024), decode_content=False)
                    if (raw is not None and hasattr(raw, "stream"))
                    else response.iter_content(chunk_size=chunk_size)
                )

                with partial_path.open(mode) as f_out:
                    for chunk in stream_iter:
                        if not chunk:
                            continue
                        # Phát hiện sớm PDF-only
                        if downloaded == 0 and (chunk.startswith(b"%PDF-") or b"%PDF-" in chunk[:16]):
                            partial_path.unlink(missing_ok=True)
                            return _STATUS_EARLY_PDF

                        downloaded += len(chunk)
                        if downloaded > max_download_bytes:
                            raise ValueError(f"Dung lượng tải vượt quá giới hạn {max_download_bytes} byte")
                        f_out.write(chunk)

                if partial_path.exists():
                    partial_path.replace(dest_path)
                return 200

        except Exception as exc:
            if attempt < max_retries:
                time.sleep((attempt + 1) * 3.0)
                attempt += 1
            else:
                partial_path.unlink(missing_ok=True)
                logger.warning("Thất bại khi tải %s sau %d lần thử: %s", url, max_retries, exc)
                return 0

    return 0


def _split_version_id(arxiv_id: str) -> tuple[str, str, str]:
    """Tách mã arXiv thành (base_id, version_tag, versioned_id).
    
    Ví dụ:
      '2412.18848v2' -> ('2412.18848', 'v2', '2412.18848v2')
      '2412.18848'   -> ('2412.18848', 'v1', '2412.18848v1')
    """
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
) -> dict:
    """Tải và giải nén mã nguồn của một phiên bản bài báo arXiv từ export.arxiv.org/src/."""
    raw_id, _ = _validate_arxiv_id(arxiv_id)
    base_id, ver, versioned_id = _split_version_id(raw_id)
    safe_base_id = base_id.replace("/", "_")

    sources_path = Path(sources_dir)
    unzipped_path = Path(unzipped_dir)
    sources_path.mkdir(parents=True, exist_ok=True)
    unzipped_path.mkdir(parents=True, exist_ok=True)

    # Đặt tên archive và thư mục giải nén theo phân cấp version độc lập: unzipped/<base_id>/<version>/
    archive_path = sources_path / f"{safe_base_id}{ver}.tar.gz"
    final_version_dir = unzipped_path / safe_base_id / ver

    req_session = session if session is not None else _get_shared_session()
    start_time = time.perf_counter()

    # DÙNG ENDPOINT CHÍNH THỨC THEO VERSION: https://export.arxiv.org/src/{versioned_id}
    url = f"https://export.arxiv.org/src/{versioned_id}"
    http_status = _download_stream(
        url,
        archive_path,
        session=req_session,
        chunk_size=CHUNK_SIZE,
        rate_limit_sec=float(rate_limit_sec),
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

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{safe_base_id}_{ver}.staging-"))
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

    # Hậu kiểm tra dọn sạch các tệp thừa (defense-in-depth)
    prune_images_and_binaries(staging_dir)
    size_after_bytes = get_dir_size_bytes(staging_dir) if staging_dir.exists() else 0

    has_tex = bool(list(staging_dir.rglob("*.tex")))
    has_bib = bool(list(staging_dir.rglob("*.bib")))

    if not has_tex:
        status = "no_latex" if has_bib else "pdf_only"
    else:
        status = "success"

    # Chuyển thư mục staging sang thư mục đích chính thức
    if final_version_dir.exists():
        shutil.rmtree(final_version_dir)
    final_version_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging_dir), str(final_version_dir))

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
) -> dict:
    """Hàm giao tiếp công khai tải và dọn mã nguồn bài báo theo phiên bản."""
    validated_id, _ = _validate_arxiv_id(arxiv_id)
    with _get_article_lock(validated_id):
        return _download_and_clean_source_impl(
            arxiv_id=arxiv_id,
            sources_dir=sources_dir,
            unzipped_dir=unzipped_dir,
            rate_limit_sec=rate_limit_sec,
            remove_archive=remove_archive,
            session=session,
        )


if __name__ == "__main__":
    print("=== TEST SOURCE DOWNLOADER (ARX-02) ===")
    test_id = "2412.18848v1"
    sources_test = "data/raw/sources_test"
    unzipped_test = "data/raw/unzipped_test"

    print(f"[*] Testing source download for: {test_id}...")
    res = download_and_clean_source(
        arxiv_id=test_id,
        sources_dir=sources_test,
        unzipped_dir=unzipped_test,
        rate_limit_sec=3.0,
        remove_archive=True,
    )

    print(f"[+] Download result:")
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
    print("[+] Test completed and cleaned up.")
