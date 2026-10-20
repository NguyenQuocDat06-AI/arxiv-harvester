"""Tải và dọn mã nguồn. Phụ trách: Nguyễn Đình Tuấn (24120237)."""

import gzip
import logging
import os
import re
import shutil
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# Kích thước chunk tải e-print theo luồng: 64 KB
CHUNK_SIZE: int = 64 * 1024

# Thời gian nghỉ tối thiểu mặc định giữa các request tới arXiv: 3.0 giây
DEFAULT_RATE_LIMIT_SEC: float = 3.0

# User-Agent định danh khi gửi request tới arXiv
DEFAULT_USER_AGENT: str = (
    "arxiv-harvester/0.1.0 (https://github.com/NguyenQuocDat06-AI/arxiv-harvester)"
)

# Danh sách phần mở rộng tệp văn bản mã nguồn cần giữ lại
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
    # Định dạng hình ảnh & đồ họa vector
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
    ".svg", ".eps", ".ps", ".pdf", ".webp", ".ico", ".ai",
    # Định dạng nhị phân, biên dịch và tệp nén
    ".pyc", ".pyd", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".tgz",
    # Dữ liệu mô hình học máy / binary data
    ".npy", ".npz", ".pkl", ".pickle", ".h5", ".hdf5", ".pt", ".pth", ".onnx",
    ".parquet", ".feather",
}

_LAST_REQUEST_TIME: float | None = None
_RATE_LIMIT_LOCK = threading.Lock()
_ARTICLE_LOCKS_GUARD = threading.Lock()
_ARTICLE_LOCKS: dict[str, threading.RLock] = {}


def _rate_limited_get(
    session: requests.Session,
    url: str,
    rate_limit_sec: float,
    **kwargs,
):
    """Bắt đầu request cách nhau tối thiểu trong các thread cùng process."""
    global _LAST_REQUEST_TIME
    if rate_limit_sec <= 0:
        return session.get(url, **kwargs)

    # Giữ lock đến khi session.get bắt đầu và trả response/raise.
    # Ghi mốc sau lời gọi get để thời gian chờ được tính từ request thực tế,
    # không phải từ lúc thread mới đặt lịch (có thể bị scheduler trì hoãn).
    with _RATE_LIMIT_LOCK:
        while _LAST_REQUEST_TIME is not None:
            elapsed = time.monotonic() - _LAST_REQUEST_TIME
            remaining = rate_limit_sec - elapsed
            if remaining <= 0:
                break
            # Một lần sleep có thể kết thúc sớm trên một số hệ điều hành;
            # kiểm tra lại monotonic clock trước khi bắt đầu request.
            time.sleep(remaining)
        try:
            return session.get(url, **kwargs)
        finally:
            _LAST_REQUEST_TIME = time.monotonic()


def _get_article_lock(arxiv_id: str) -> threading.RLock:
    """Lấy lock theo bài để hai lần tải cùng ID không ghi đè file của nhau."""
    with _ARTICLE_LOCKS_GUARD:
        lock = _ARTICLE_LOCKS.get(arxiv_id)
        if lock is None:
            lock = threading.RLock()
            _ARTICLE_LOCKS[arxiv_id] = lock
        return lock


def reset_rate_limiter() -> None:
    """Đặt lại mốc rate limit; chỉ dùng khi không có request đang chạy (ví dụ unit test)."""
    global _LAST_REQUEST_TIME
    with _RATE_LIMIT_LOCK:
        _LAST_REQUEST_TIME = None


def get_dir_size_bytes(path: str | Path) -> int:
    """Đo tổng dung lượng (byte) của các tệp thông thường trong thư mục, bao gồm thư mục con.

    Quy tắc:
    - Không cộng kích thước thư mục.
    - Không theo liên kết mềm (symlink) và không tính tệp bên ngoài qua symlink.
    - Tính dung lượng theo từng đường dẫn tệp thông thường; hard link có thể được tính theo từng tên tệp.
    - Phân biệt rõ đường dẫn đầu vào không hợp lệ với lỗi xảy ra khi duyệt tệp con:
      + Báo FileNotFoundError nếu thư mục không tồn tại hoặc đường dẫn rỗng.
      + Báo NotADirectoryError nếu đường dẫn tồn tại nhưng không phải là thư mục.
      + Không che giấu lỗi đọc metadata/truy cập ở tệp hoặc thư mục con (báo OSError).

    Args:
        path: Đường dẫn thư mục cần đo dung lượng (str hoặc Path).

    Returns:
        int: Tổng kích thước theo byte của các tệp thông thường.

    Raises:
        TypeError: Nếu path không phải là chuỗi hoặc Path/PathLike.
        FileNotFoundError: Nếu đường dẫn rỗng hoặc không tồn tại.
        NotADirectoryError: Nếu đường dẫn tồn tại nhưng không phải là thư mục.
        OSError: Nếu không thể đọc metadata hoặc truy cập tệp/thư mục con trong quá trình duyệt.
    """
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
                # Bỏ qua symlink; không theo liên kết ra ngoài thư mục.
                if entry.is_symlink():
                    continue

                if entry.is_dir(follow_symlinks=False):
                    total += _scan_dir(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    # Đếm từng đường dẫn tệp. st_ino không đáng tin cậy trên mọi filesystem/OS.
                    total += entry.stat(follow_symlinks=False).st_size
        return total

    return _scan_dir(root_path)


def prune_images_and_binaries(path: str | Path) -> None:
    """Dọn ảnh và tệp nhị phân trong thư mục nguồn đã giải nén.

    Quy tắc:
    - Giữ lại các tệp mã nguồn văn bản: .tex, .bib, .bbl, .sty, .cls, .bst, .txt.
    - Loại bỏ toàn bộ các tệp ảnh/đồ họa (.png, .jpg, .jpeg, .pdf, .eps, .ps, .svg, .bmp, .tif, .gif,...)
      và các tệp nhị phân/dữ liệu nén không phải văn bản.
    - Chỉ thao tác an toàn bên trong thư mục bài báo đã kiểm tra; loại bỏ liên kết mềm (symlink)
      để phòng tránh rủi ro thoát thư mục.

    Args:
        path: Đường dẫn thư mục bài báo đã giải nén.

    Raises:
        TypeError: Nếu path không phải là str hoặc Path/PathLike.
        FileNotFoundError: Nếu đường dẫn không tồn tại hoặc rỗng.
        NotADirectoryError: Nếu đường dẫn không phải là thư mục.
    """
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

    root_dir = Path(path).resolve()

    for root, _, files in os.walk(root_dir, topdown=False, followlinks=False):
        current_dir = Path(root)

        for file_name in files:
            file_path = current_dir / file_name

            # Nếu là liên kết mềm (symlink): xóa ngay để tránh rủi ro bảo mật
            if file_path.is_symlink():
                file_path.unlink(missing_ok=True)
                continue

            # Đảm bảo đường dẫn tệp nằm hoàn toàn bên trong thư mục bài báo
            try:
                resolved_file = file_path.resolve()
                if not resolved_file.is_relative_to(root_dir):
                    file_path.unlink(missing_ok=True)
                    continue
            except (OSError, ValueError):
                file_path.unlink(missing_ok=True)
                continue

            ext = file_path.suffix.lower()

            # Nếu tệp thuộc nhóm ảnh/nhị phân hoặc không thuộc danh sách tệp văn bản cần giữ
            if ext in IMAGE_AND_BINARY_EXTENSIONS or ext not in KEEP_EXTENSIONS:
                try:
                    file_path.unlink(missing_ok=True)
                except OSError as exc:
                    raise OSError(f"Không thể dọn tệp không cần thiết {file_path}: {exc}") from exc

        # Dọn dẹp thư mục con nếu đã rỗng sau khi xóa tệp
        if current_dir != root_dir:
            try:
                if not any(current_dir.iterdir()):
                    current_dir.rmdir()
            except OSError:
                pass


def _safe_extract_tar(
    tar: tarfile.TarFile,
    dest_dir: Path,
    max_total_bytes: int = 500 * 1024 * 1024,
    max_members: int = 50_000,
) -> None:
    """Giải nén tar theo allowlist; từ chối archive không an toàn thay vì bỏ qua member."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    root = dest_dir.resolve()
    members = tar.getmembers()
    if len(members) > max_members:
        raise ValueError(f"Archive có quá nhiều thành viên: {len(members)} > {max_members}")

    total_bytes = 0
    seen: set[str] = set()
    for member in members:
        # Chuẩn hóa separator trước khi kiểm tra để chặn cả đường dẫn kiểu Windows.
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
        # Tar có thể lặp entry thư mục; cho phép lặp thư mục, không cho ghi đè file.
        if normalized in seen and not member.isdir():
            raise ValueError(f"Thành viên bị trùng trong archive: {member.name!r}")
        if normalized in seen and member.isdir():
            continue
        seen.add(normalized)

        if not (member.isdir() or member.isfile()):
            raise ValueError(f"Loại thành viên archive không được hỗ trợ: {member.name!r}")
        if member.size < 0:
            raise ValueError(f"Kích thước thành viên không hợp lệ: {member.name!r}")
        total_bytes += member.size
        if total_bytes > max_total_bytes:
            raise ValueError(f"Dung lượng giải nén vượt giới hạn {max_total_bytes} byte")

        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
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


def _extract_single_gz(
    archive_path: Path,
    dest_dir: Path,
    arxiv_id: str,
    max_output_bytes: int = 500 * 1024 * 1024,
) -> None:
    """Giải nén gzip đơn lẻ theo luồng và chặn dữ liệu sau giải nén quá lớn."""
    safe_id = arxiv_id.replace("/", "_")
    target_tex = dest_dir / f"{safe_id}.tex"
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


def _download_stream(
    url: str,
    dest_path: Path,
    session: requests.Session,
    max_retries: int = 3,
    chunk_size: int = CHUNK_SIZE,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
    max_download_bytes: int = 250 * 1024 * 1024,
) -> int:
    """Tải theo luồng vào .part, giới hạn kích thước và chỉ publish sau khi tải đủ."""
    partial_path = dest_path.with_name(dest_path.name + ".part")
    for attempt in range(1, max_retries + 1):
        partial_path.unlink(missing_ok=True)
        try:
            with _rate_limited_get(
                session,
                url,
                rate_limit_sec,
                stream=True,
                timeout=(10.0, 30.0),
            ) as response:
                if response.status_code == 404:
                    partial_path.unlink(missing_ok=True)
                    return 404
                if response.status_code != 200:
                    response.raise_for_status()
                    raise requests.RequestException(
                        f"HTTP status không mong đợi: {response.status_code}"
                    )

                downloaded = 0
                with partial_path.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > max_download_bytes:
                            raise ValueError(
                                f"Archive vượt giới hạn tải {max_download_bytes} byte"
                            )
                        output.write(chunk)
                if downloaded == 0:
                    raise ValueError("Response tải về rỗng")
            os.replace(partial_path, dest_path)
            return 200
        except (requests.RequestException, OSError, ValueError) as exc:
            partial_path.unlink(missing_ok=True)
            if attempt < max_retries:
                time.sleep(min(2.0 ** attempt, 8.0))
            else:
                logger.warning("Thất bại khi tải %s sau %d lần thử: %s", url, max_retries, exc)
                return 0
    return 0


def _validate_arxiv_id(arxiv_id: str) -> tuple[str, str]:
    """Xác thực mã arXiv và trả về (mã gốc, tên thư mục an toàn)."""
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
    """Tải e-print theo luồng 64 KB, kiểm tra định dạng, giải nén và đo dọn hình ảnh.

    Quy trình:
    1. Kiểm soát tốc độ gọi (rate limit) tối thiểu rate_limit_sec giữa các request.
    2. Tải e-print từ https://export.arxiv.org/e-print/{arxiv_id} theo luồng chunk 64 KB.
    3. Phân biệt định dạng qua byte đầu hoặc cấu trúc archive:
       - Nếu là PDF-only (%PDF-): không giải nén, ghi nhận trạng thái 'pdf_only'.
       - Nếu là lỗi 404: ghi nhận 'not_found'.
       - Nếu là gói .tar.gz hoặc .gz đơn: giải nén an toàn vào unzipped_dir/{arxiv_id}/.
    4. Kiểm tra mã nguồn LaTeX (.tex): nếu không có tệp .tex nào, ghi nhận 'no_latex'.
    5. Đo dung lượng trước dọn dẹp (size_before_bytes).
    6. Dọn ảnh/nhị phân bằng prune_images_and_binaries và đo lại (size_after_bytes).
    7. Xóa tệp nén tạm thời theo cờ remove_archive.

    Args:
        arxiv_id: Mã bài báo arXiv (ví dụ: '2502.03235').
        sources_dir: Thư mục chứa archive tải về (ví dụ: 'data/raw/sources').
        unzipped_dir: Thư mục chứa nguồn đã giải nén (ví dụ: 'data/raw/unzipped').
        rate_limit_sec: Số giây nghỉ tối thiểu giữa các request (mặc định 3.0s).
        remove_archive: Có xóa gói nén sau khi giải nén hay không (mặc định True).
        session: Session requests tùy chọn (nếu None sẽ dùng session tạo tự động).

    Returns:
        dict: {
            'arxiv_id': str,
            'status': str,  # 'success', 'pdf_only', 'not_found', 'no_latex', 'error'
            'size_before_bytes': int,
            'size_after_bytes': int,
            'elapsed_sec': float
        }
    """
    arxiv_id, safe_id = _validate_arxiv_id(arxiv_id)
    if isinstance(rate_limit_sec, bool) or not isinstance(rate_limit_sec, (int, float)):
        raise TypeError("rate_limit_sec phải là số")
    if rate_limit_sec < 0:
        raise ValueError("rate_limit_sec không được âm")
    if not isinstance(remove_archive, bool):
        raise TypeError("remove_archive phải là bool")
    if not isinstance(sources_dir, str) or not sources_dir.strip():
        raise ValueError("sources_dir không được để trống")
    if not isinstance(unzipped_dir, str) or not unzipped_dir.strip():
        raise ValueError("unzipped_dir không được để trống")

    sources_path = Path(sources_dir)
    unzipped_path = Path(unzipped_dir)
    sources_path.mkdir(parents=True, exist_ok=True)
    unzipped_path.mkdir(parents=True, exist_ok=True)

    archive_path = sources_path / f"{safe_id}.tar.gz"
    final_paper_dir = unzipped_path / safe_id
    # Chỉ tạo staging sau khi xác nhận response không phải PDF-only/lỗi HTTP.
    paper_unzipped_dir = unzipped_path / f".{safe_id}.staging-pending"

    owns_session = session is None
    req_session = session if session is not None else requests.Session()
    if "User-Agent" not in req_session.headers:
        req_session.headers["User-Agent"] = DEFAULT_USER_AGENT

    start_time = time.perf_counter()

    url = f"https://export.arxiv.org/e-print/{arxiv_id}"
    try:
        http_status = _download_stream(
            url,
            archive_path,
            session=req_session,
            chunk_size=CHUNK_SIZE,
            rate_limit_sec=float(rate_limit_sec),
        )
    finally:
        if owns_session:
            req_session.close()

    elapsed_sec = round(time.perf_counter() - start_time, 3)

    if http_status == 404:
        return {
            "arxiv_id": arxiv_id,
            "status": "not_found",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
        }
    if http_status != 200 or not archive_path.exists():
        return {
            "arxiv_id": arxiv_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
        }

    # Đọc byte đầu để nhận diện định dạng
    try:
        with open(archive_path, "rb") as f:
            header_bytes = f.read(1024)
    except OSError:
        if remove_archive and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": arxiv_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
        }

    # Trường hợp 1: Bài báo chỉ có tệp PDF (%PDF-)
    if header_bytes.startswith(b"%PDF-") or b"%PDF-" in header_bytes[:16]:
        if remove_archive and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": arxiv_id,
            "status": "pdf_only",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
        }

    # Trường hợp 2: Nội dung trả về là HTML thông báo lỗi
    lower_header = header_bytes[:200].lower()
    if b"<!doctype html" in lower_header or b"<html" in lower_header:
        if remove_archive and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": arxiv_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
        }

    # Giải nén vào staging riêng để giữ nguyên bản kết quả trước đó nếu có lỗi.
    paper_unzipped_dir = Path(tempfile.mkdtemp(prefix=f".{safe_id}.staging-", dir=unzipped_path))

    # Tiến hành giải nén theo định dạng thực tế
    extracted_ok = False
    try:
        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:*") as tar:
                _safe_extract_tar(tar, paper_unzipped_dir)
            extracted_ok = True
        elif header_bytes.startswith(b"\x1f\x8b"):
            _extract_single_gz(archive_path, paper_unzipped_dir, arxiv_id)
            extracted_ok = True
        else:
            # Chỉ chấp nhận plain text có dấu hiệu LaTeX; không biến response lạ thành .tex.
            with archive_path.open("rb") as source_file:
                sample = source_file.read(64 * 1024)
            try:
                sample_text = sample.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Response không phải tar/gzip/PDF hoặc TeX UTF-8 hợp lệ") from exc
            if not any(marker in sample_text for marker in (r"\documentclass", r"\begin{document}", r"\input", r"\section")):
                raise ValueError("Response không nhận diện được là mã nguồn LaTeX")
            target_tex = paper_unzipped_dir / f"{safe_id}.tex"
            shutil.copyfile(archive_path, target_tex)
            extracted_ok = True
    except Exception as e:
        logger.warning("Lỗi khi giải nén bài báo %s: %s", arxiv_id, e)
        extracted_ok = False

    if not extracted_ok:
        if paper_unzipped_dir.exists():
            shutil.rmtree(paper_unzipped_dir, ignore_errors=True)
        if remove_archive and archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return {
            "arxiv_id": arxiv_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": elapsed_sec,
        }

    # Kiểm tra xem mã nguồn giải nén có chứa tệp LaTeX (.tex) hay không
    tex_files = list(paper_unzipped_dir.rglob("*.tex"))
    if not tex_files:
        try:
            size_before = get_dir_size_bytes(paper_unzipped_dir)
        except OSError as exc:
            logger.warning("Không thể đo nguồn không có TeX %s: %s", arxiv_id, exc)
            shutil.rmtree(paper_unzipped_dir, ignore_errors=True)
            return {
                "arxiv_id": arxiv_id,
                "status": "error",
                "size_before_bytes": 0,
                "size_after_bytes": 0,
                "elapsed_sec": round(time.perf_counter() - start_time, 3),
            }
        shutil.rmtree(paper_unzipped_dir, ignore_errors=True)
        if remove_archive and archive_path.exists():
            try:
                archive_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                logger.warning("Không xóa được archive %s: %s", archive_path, cleanup_exc)
        return {
            "arxiv_id": arxiv_id,
            "status": "no_latex",
            "size_before_bytes": size_before,
            "size_after_bytes": size_before,
            "elapsed_sec": round(time.perf_counter() - start_time, 3),
        }

    # Đo và dọn trong khối có kiểm soát; nếu thao tác file thất bại thì không publish.
    try:
        size_before_bytes = get_dir_size_bytes(paper_unzipped_dir)
        prune_images_and_binaries(paper_unzipped_dir)
        size_after_bytes = get_dir_size_bytes(paper_unzipped_dir)
    except OSError as exc:
        logger.warning("Không thể đo/dọn nguồn %s: %s", arxiv_id, exc)
        shutil.rmtree(paper_unzipped_dir, ignore_errors=True)
        return {
            "arxiv_id": arxiv_id,
            "status": "error",
            "size_before_bytes": 0,
            "size_after_bytes": 0,
            "elapsed_sec": round(time.perf_counter() - start_time, 3),
        }

    # Đảm bảo tính nhất quán: size_after <= size_before
    if size_after_bytes > size_before_bytes:
        logger.error(
            "Dung lượng sau dọn (%d) lớn hơn trước (%d) tại %s",
            size_after_bytes,
            size_before_bytes,
            paper_unzipped_dir,
        )
        shutil.rmtree(paper_unzipped_dir, ignore_errors=True)
        return {
            "arxiv_id": arxiv_id,
            "status": "error",
            "size_before_bytes": size_before_bytes,
            "size_after_bytes": size_after_bytes,
            "elapsed_sec": round(time.perf_counter() - start_time, 3),
        }

    # Chỉ thay bản kết quả cũ sau khi tải, giải nén, xác thực và dọn dẹp đều thành công.
    backup_dir = unzipped_path / f".{safe_id}.backup"
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if final_paper_dir.exists():
            os.replace(final_paper_dir, backup_dir)
        try:
            os.replace(paper_unzipped_dir, final_paper_dir)
        except OSError:
            if backup_dir.exists() and not final_paper_dir.exists():
                os.replace(backup_dir, final_paper_dir)
            raise
        if backup_dir.exists():
            try:
                shutil.rmtree(backup_dir)
            except OSError as cleanup_exc:
                logger.warning("Đã publish nguồn %s nhưng không xóa được backup %s: %s", arxiv_id, backup_dir, cleanup_exc)
    except OSError as exc:
        logger.exception("Không thể cập nhật thư mục nguồn %s: %s", arxiv_id, exc)
        if paper_unzipped_dir.exists():
            shutil.rmtree(paper_unzipped_dir, ignore_errors=True)
        return {
            "arxiv_id": arxiv_id,
            "status": "error",
            "size_before_bytes": size_before_bytes,
            "size_after_bytes": size_after_bytes,
            "elapsed_sec": round(time.perf_counter() - start_time, 3),
        }

    # Xóa gói nén tạm nếu được yêu cầu
    if remove_archive and archive_path.exists():
        try:
            archive_path.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            logger.warning("Không xóa được archive %s sau khi xử lý thành công: %s", archive_path, cleanup_exc)

    elapsed_sec = round(time.perf_counter() - start_time, 3)

    return {
        "arxiv_id": arxiv_id,
        "status": "success",
        "size_before_bytes": size_before_bytes,
        "size_after_bytes": size_after_bytes,
        "elapsed_sec": elapsed_sec,
    }


def download_and_clean_source(
    arxiv_id: str,
    sources_dir: str,
    unzipped_dir: str,
    rate_limit_sec: float = 3.0,
    remove_archive: bool = True,
) -> dict:
    # Trả ra trạng thái tải, size_before_bytes, size_after_bytes và elapse seconds
    validated_id, _ = _validate_arxiv_id(arxiv_id)
    with _get_article_lock(validated_id):
        return _download_and_clean_source_impl(
            arxiv_id=arxiv_id,
            sources_dir=sources_dir,
            unzipped_dir=unzipped_dir,
            rate_limit_sec=rate_limit_sec,
            remove_archive=remove_archive,
        )
