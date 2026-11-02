"""Schema và ghi Parquet chuẩn hóa cho arXiv Harvester.

Phụ trách: Dương Phan Minh Trí (24120470) — Nhánh feat/data-storage.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


# Metadata và trạng thái nguồn theo version.
VERSION_STRUCT_TYPE = pa.struct([
    pa.field("version", pa.string(), nullable=True),
    pa.field("created", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("size_before_bytes", pa.int64(), nullable=True),
    pa.field("size_after_bytes", pa.int64(), nullable=True),
    pa.field("source_status", pa.string(), nullable=True),
])

# Bảng publications nội bộ.
PUBLICATIONS_SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("title", pa.string(), nullable=True),
    pa.field("abstract", pa.string(), nullable=True),
    pa.field("authors", pa.list_(pa.string()), nullable=True),
    pa.field("primary_category", pa.string(), nullable=True),
    pa.field("categories", pa.list_(pa.string()), nullable=True),
    pa.field("published", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("updated", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("doi", pa.string(), nullable=True),
    pa.field("journal_ref", pa.string(), nullable=True),
    pa.field("comments", pa.string(), nullable=True),
    pa.field("venue", pa.string(), nullable=True),
    pa.field("source_status", pa.string(), nullable=True),
    pa.field("size_before_bytes", pa.int64(), nullable=True),
    pa.field("size_after_bytes", pa.int64(), nullable=True),
    pa.field("versions", pa.list_(VERSION_STRUCT_TYPE), nullable=True),
])

# Bảng references nội bộ.
REFERENCES_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("ref_arxiv_id", pa.string(), nullable=True),
    pa.field("ref_title", pa.string(), nullable=True),
    pa.field("ref_authors", pa.list_(pa.string()), nullable=True),
    pa.field("ref_submission_date", pa.string(), nullable=True),
    pa.field("ref_s2_id", pa.string(), nullable=True),  # Semantic Scholar paperId.
    pa.field("ref_doi", pa.string(), nullable=True),
    pa.field("ref_year", pa.int32(), nullable=True),
    pa.field("ref_venue", pa.string(), nullable=True),
    pa.field("raw_citation", pa.string(), nullable=True),
    pa.field("source", pa.string(), nullable=True),
])

# Schema chuẩn nộp bài theo đề Lab Book Milestone 1
COURSE_PAPERS_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("title", pa.string(), nullable=True),
    pa.field("authors", pa.list_(pa.string()), nullable=True),
    pa.field("submission_date", pa.string(), nullable=True),
    pa.field("revised_dates", pa.list_(pa.string()), nullable=True),
    pa.field("venue", pa.string(), nullable=True),
])

COURSE_REFERENCES_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("ref_arxiv_id", pa.string(), nullable=False),
    pa.field("ref_title", pa.string(), nullable=True),
    pa.field("ref_authors", pa.list_(pa.string()), nullable=True),
    pa.field("ref_submission_date", pa.string(), nullable=True),
    pa.field("ref_s2_id", pa.string(), nullable=True),
])

VALID_SOURCE_STATUSES = frozenset({"success", "partial_success", "pdf_only", "no_latex", "error", "not_found", "pending"})
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")
_WARNED_UNKNOWN_STATUSES: set[str] = set()
_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PAPERS_WITH_SYNTHESIZED_V1_COUNT: int = 0
_DROPPED_REF_DATES_COUNT: int = 0


def get_synthesized_v1_count() -> int:
    """Số bài được bổ sung version v1 mặc định."""
    return _PAPERS_WITH_SYNTHESIZED_V1_COUNT


def reset_synthesized_v1_count() -> None:
    """Đặt lại bộ đếm version v1 mặc định."""
    global _PAPERS_WITH_SYNTHESIZED_V1_COUNT
    _PAPERS_WITH_SYNTHESIZED_V1_COUNT = 0


def get_dropped_ref_dates_count() -> int:
    """Số ngày trích dẫn không hợp lệ đã loại bỏ."""
    return _DROPPED_REF_DATES_COUNT


def reset_dropped_ref_dates_count() -> None:
    """Đặt lại bộ đếm ngày bị loại bỏ."""
    global _DROPPED_REF_DATES_COUNT
    _DROPPED_REF_DATES_COUNT = 0


def _parse_version_num(ver_str: Any) -> int:
    """Lấy số thứ tự version, ví dụ v12 thành 12."""
    m = re.search(r"\d+", str(ver_str))
    return int(m.group()) if m else 999999


# Tiện ích Chuẩn hóa & Hỗ trợ Round-trip


def _is_null(val: Any) -> bool:
    """Nhận diện None, NaN, pd.NA và pd.NaT; giữ nguyên các chuỗi cùng tên."""
    if val is None:
        return True
    if isinstance(val, str):
        return False
    if isinstance(val, float) and math.isnan(val):
        return True
    type_name = type(val).__name__
    if type_name in ("NAType", "NaTType"):
        return True
    try:
        if math.isnan(val):
            return True
    except (TypeError, ValueError):
        pass
    return False


def _to_clean_string(val: Any) -> str | None:
    """Rút gọn khoảng trắng; trả None nếu rỗng hoặc null."""
    if _is_null(val):
        return None
    s = str(val).strip()
    return " ".join(s.split()) if s else None


def _to_utc_timestamp(val: Any) -> datetime | None:
    """Chuyển thời gian sang UTC."""
    if _is_null(val):
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    # Nếu là chuỗi ISO
    s = str(val).strip()
    if not s:
        return None
    try:
        # Thay đuôi Z bằng +00:00 cho fromisoformat nếu cần
        clean_iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _to_string_list(val: Any) -> list[str]:
    """Chuyển list, tuple hoặc ndarray thành list[str]; null thành []."""
    if _is_null(val):
        return []
    if isinstance(val, str):
        # Tránh trường hợp chuỗi đơn bị duyệt từng ký tự
        cleaned = _to_clean_string(val)
        return [cleaned] if cleaned else []
    if isinstance(val, Iterable):
        res = []
        for item in val:
            cleaned = _to_clean_string(item)
            if cleaned:
                res.append(cleaned)
        return res
    return []


def _to_non_negative_int(val: Any) -> int | None:
    """Đổi sang số nguyên không âm; giá trị không hợp lệ thành None."""
    if _is_null(val):
        return None
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        n = int(val)
        return n if n >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _validate_ref_submission_date(val: Any) -> str | None:
    """Kiểm tra ngày YYYY-MM-DD và đếm ngày lỗi; không suy ngày từ ref_year."""
    global _DROPPED_REF_DATES_COUNT
    if _is_null(val):
        return None
    s = str(val).strip()
    if not s:
        return None
    if not _DATE_REGEX.match(s):
        _DROPPED_REF_DATES_COUNT += 1
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        _DROPPED_REF_DATES_COUNT += 1
        return None


def _clean_base_id(val: Any) -> str | None:
    """Bỏ khoảng trắng và hậu tố version khỏi arXiv ID."""
    s = _to_clean_string(val)
    if not s:
        return None
    return _VERSION_SUFFIX_RE.sub("", s)


def resolve_paper_source_status(statuses: list[str | None]) -> str | None:
    """Tổng hợp trạng thái các version.

    Toàn bộ success: success; chỉ một phần success: partial_success.
    Nếu không có success, ưu tiên error, no_latex, rồi pdf_only.
    """
    if not statuses or not any(st in VALID_SOURCE_STATUSES for st in statuses):
        return None
    clean = [st if st in VALID_SOURCE_STATUSES else "pending" for st in statuses]
    if all(st == "success" for st in clean):
        return "success"
    if any(st == "success" for st in clean):
        return "partial_success"
    if "error" in clean:
        return "error"
    if "not_found" in clean:
        return "not_found"
    if "pending" in clean:
        return "pending"
    if "no_latex" in clean:
        return "no_latex"
    if "pdf_only" in clean:
        return "pdf_only"
    return clean[0]


# Chuẩn hóa Bản ghi (Normalizer) & Phân loại Hỏng


def normalize_publication_record(record: dict[str, Any], index: int = 0) -> tuple[dict[str, Any] | None, list[str]]:
    """Chuẩn hóa publication; trả None nếu thiếu ID."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return None, [f"Bản ghi index {index} không phải là dict (kiểu: {type(record).__name__})"]

    raw_id = record.get("id") or record.get("arxiv_id")
    paper_id = _clean_base_id(raw_id)
    if not paper_id:
        return None, [f"Bản ghi index {index} mất hẳn id hoặc id rỗng (raw: {raw_id!r})"]

    title = _to_clean_string(record.get("title"))
    abstract = _to_clean_string(record.get("abstract"))
    authors = _to_string_list(record.get("authors"))
    primary_category = _to_clean_string(record.get("primary_category"))
    categories = _to_string_list(record.get("categories"))

    published = _to_utc_timestamp(record.get("published"))
    updated = _to_utc_timestamp(record.get("updated"))

    doi = _to_clean_string(record.get("doi"))
    journal_ref = _to_clean_string(record.get("journal_ref"))
    comments = _to_clean_string(record.get("comments") or record.get("comment"))
    venue = _to_clean_string(record.get("venue") or journal_ref)

    # Xử lý dung lượng và trạng thái cấp bài
    size_before = _to_non_negative_int(record.get("size_before_bytes"))
    size_after = _to_non_negative_int(record.get("size_after_bytes"))
    raw_status = record.get("source_status") or record.get("status")
    source_status = _to_clean_string(raw_status)
    if source_status is not None and source_status not in VALID_SOURCE_STATUSES:
        if source_status not in _WARNED_UNKNOWN_STATUSES:
            _WARNED_UNKNOWN_STATUSES.add(source_status)
            logger.warning("Trạng thái nguồn lạ '%s' được chuyển thành None", source_status)
        source_status = None

    # Xử lý struct versions
    raw_versions = record.get("versions")
    clean_versions = []
    if isinstance(raw_versions, Iterable) and not isinstance(raw_versions, (str, bytes)):
        for v in raw_versions:
            if isinstance(v, dict):
                v_num = _to_clean_string(v.get("version")) or "v1"
                v_created = _to_utc_timestamp(v.get("created"))
                v_sb = _to_non_negative_int(v.get("size_before_bytes"))
                v_sa = _to_non_negative_int(v.get("size_after_bytes"))
                raw_v_st = v.get("source_status") or v.get("status")
                v_st = _to_clean_string(raw_v_st)
                if v_st is not None and v_st not in VALID_SOURCE_STATUSES:
                    if v_st not in _WARNED_UNKNOWN_STATUSES:
                        _WARNED_UNKNOWN_STATUSES.add(v_st)
                        logger.warning("Trạng thái nguồn version lạ '%s' được chuyển thành None", v_st)
                    v_st = None
                clean_versions.append({
                    "version": v_num,
                    "created": v_created,
                    "size_before_bytes": v_sb,
                    "size_after_bytes": v_sa,
                    "source_status": v_st,
                })

    # Sắp xếp version theo số thứ tự.
    if clean_versions:
        clean_versions.sort(key=lambda x: _parse_version_num(x.get("version")))

    # Bổ sung v1 nếu thiếu danh sách versions.
    if not clean_versions:
        global _PAPERS_WITH_SYNTHESIZED_V1_COUNT
        _PAPERS_WITH_SYNTHESIZED_V1_COUNT += 1
        logger.warning(
            "Bài báo %s không có version nào từ thượng nguồn; tự động tổng hợp v1 mặc định.",
            paper_id,
        )
        clean_versions = [{
            "version": "v1",
            "created": published or updated,
            "size_before_bytes": size_before,
            "size_after_bytes": size_after,
            "source_status": source_status,
        }]
    else:
        # Nếu chỉ có số đo cấp bài, gán cho version cuối.

        has_any_version_metric = any(v["source_status"] is not None or v["size_before_bytes"] is not None for v in clean_versions)
        if not has_any_version_metric and (source_status is not None or size_before is not None or size_after is not None):
            clean_versions[-1]["size_before_bytes"] = size_before
            clean_versions[-1]["size_after_bytes"] = size_after
            clean_versions[-1]["source_status"] = source_status

    # Tổng hợp từ versions nếu cấp bài thiếu số đo.
    if size_before is None:
        v_sizes_before = [v["size_before_bytes"] for v in clean_versions if v["size_before_bytes"] is not None]
        if v_sizes_before:
            size_before = sum(v_sizes_before)

    if size_after is None:
        v_sizes_after = [v["size_after_bytes"] for v in clean_versions if v["size_after_bytes"] is not None]
        if v_sizes_after:
            size_after = sum(v_sizes_after)

    if source_status is None or any(v["source_status"] is not None for v in clean_versions):
        source_status = resolve_paper_source_status([v["source_status"] for v in clean_versions])

    normalized = {
        "id": paper_id,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "primary_category": primary_category,
        "categories": categories,
        "published": published,
        "updated": updated,
        "doi": doi,
        "journal_ref": journal_ref,
        "comments": comments,
        "venue": venue,
        "source_status": source_status,
        "size_before_bytes": size_before,
        "size_after_bytes": size_after,
        "versions": clean_versions,
    }
    return normalized, errors


def normalize_reference_record(record: dict[str, Any], index: int = 0) -> tuple[dict[str, Any] | None, list[str]]:
    """Chuẩn hóa reference; trả None nếu thiếu ID bài nguồn."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return None, [f"Bản ghi index {index} không phải là dict (kiểu: {type(record).__name__})"]

    raw_source_id = record.get("arxiv_id") or record.get("source_id")
    arxiv_id = _clean_base_id(raw_source_id)
    if not arxiv_id:
        return None, [f"Bản ghi index {index} mất hẳn arxiv_id bài nguồn (raw: {raw_source_id!r})"]

    ref_arxiv_id = _clean_base_id(record.get("ref_arxiv_id") or record.get("arxiv_id_ref"))
    ref_title = _to_clean_string(record.get("ref_title") or record.get("title"))
    ref_authors = _to_string_list(record.get("ref_authors") or record.get("authors"))

    ref_sub_date = _validate_ref_submission_date(record.get("ref_submission_date"))
    ref_s2_id = _to_clean_string(record.get("ref_s2_id") or record.get("paperId"))
    ref_doi = _to_clean_string(record.get("ref_doi") or record.get("doi"))
    if ref_doi:
        ref_doi = re.sub(r"^(?:https?://doi\.org/|doi:)", "", ref_doi, flags=re.I).strip()

    ref_year = _to_non_negative_int(record.get("ref_year") or record.get("year"))
    ref_venue = _to_clean_string(record.get("ref_venue") or record.get("venue"))
    raw_citation = _to_clean_string(record.get("raw_citation"))
    source = _to_clean_string(record.get("source") or record.get("extraction_source"))

    normalized = {
        "arxiv_id": arxiv_id,
        "ref_arxiv_id": ref_arxiv_id,
        "ref_title": ref_title,
        "ref_authors": ref_authors,
        "ref_submission_date": ref_sub_date,
        "ref_s2_id": ref_s2_id,
        "ref_doi": ref_doi,
        "ref_year": ref_year,
        "ref_venue": ref_venue,
        "raw_citation": raw_citation,
        "source": source,
    }
    return normalized, errors


# Ghi File Nguyên Tử & Quản lý Rejected


def _write_parquet_atomic(table: pa.Table, output_path: str, compression: str = "snappy") -> None:
    """Ghi Parquet qua tệp tạm cùng thư mục rồi rename."""
    directory = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{output_path}.tmp.{os.getpid()}"
    try:
        pq.write_table(table, tmp_path, compression=compression)
        os.replace(tmp_path, output_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _quarantine_rejected_records(rejected: list[tuple[dict[str, Any], list[str]]], output_path: str) -> None:
    """Lưu bản ghi lỗi vào JSONL; bỏ qua dòng đã có."""
    if not rejected:
        return
    directory = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(directory, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(output_path))[0]
    rejected_path = os.path.join(directory, f"_rejected_{base_name}.jsonl")

    existing_lines: set[str] = set()
    if os.path.exists(rejected_path):
        try:
            with open(rejected_path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        existing_lines.add(s)
        except OSError:
            pass

    new_lines: list[str] = []
    for rec, errs in rejected:
        line_str = json.dumps({"record": rec, "errors": errs}, ensure_ascii=False, default=str, sort_keys=True)
        if line_str not in existing_lines:
            existing_lines.add(line_str)
            new_lines.append(line_str)

    if new_lines:
        with open(rejected_path, "a", encoding="utf-8") as f:
            for l in new_lines:
                f.write(l + "\n")
        logger.warning("Đã cách ly %d bản ghi hỏng mới vào %s", len(new_lines), rejected_path)


# Giao diện Ghi Parquet Chính thức


def save_publications_parquet(
    records: list[dict],
    output_path: str,
    on_invalid: str = "quarantine",
) -> None:
    """Ghi publications theo schema. on_invalid chọn quarantine hoặc raise."""
    valid_records: list[dict] = []
    rejected: list[tuple[dict, list[str]]] = []
    all_errors: list[str] = []

    for idx, rec in enumerate(records):
        norm, errs = normalize_publication_record(rec, index=idx)
        if norm is not None:
            valid_records.append(norm)
        else:
            rejected.append((rec, errs))
            all_errors.extend(errs)

    if on_invalid == "raise" and all_errors:
        raise ValueError(f"Phát hiện {len(all_errors)} lỗi dữ liệu trong publications:\n" + "\n".join(all_errors))

    if rejected:
        _quarantine_rejected_records(rejected, output_path)


    if valid_records:
        table = pa.Table.from_pylist(valid_records, schema=PUBLICATIONS_SCHEMA)
    else:
        table = PUBLICATIONS_SCHEMA.empty_table()

    _write_parquet_atomic(table, output_path, compression="snappy")


def save_references_parquet(
    records: list[dict],
    output_path: str,
    on_invalid: str = "quarantine",
) -> None:
    """Ghi references theo schema."""
    valid_records: list[dict] = []
    rejected: list[tuple[dict, list[str]]] = []
    all_errors: list[str] = []

    for idx, rec in enumerate(records):
        norm, errs = normalize_reference_record(rec, index=idx)
        if norm is not None:
            valid_records.append(norm)
        else:
            rejected.append((rec, errs))
            all_errors.extend(errs)

    if on_invalid == "raise" and all_errors:
        raise ValueError(f"Phát hiện {len(all_errors)} lỗi dữ liệu trong references:\n" + "\n".join(all_errors))

    if rejected:
        _quarantine_rejected_records(rejected, output_path)

    if valid_records:
        table = pa.Table.from_pylist(valid_records, schema=REFERENCES_SCHEMA)
    else:
        table = REFERENCES_SCHEMA.empty_table()

    _write_parquet_atomic(table, output_path, compression="snappy")


# Hàm Xuất Sang Chuẩn Đề Môn Học (export_to_course_spec)


def export_to_course_spec(processed_dir: str, export_dir: str) -> tuple[str, str]:
    """Xuất hai bảng sáu cột theo đề.

    papers lấy ngày v1 và các ngày revision đã biết. references chỉ giữ
    cạnh có ref_arxiv_id và khử trùng theo cặp (arxiv_id, ref_arxiv_id).
    """
    os.makedirs(export_dir, exist_ok=True)
    pub_in = os.path.join(processed_dir, "publications.parquet")
    ref_in = os.path.join(processed_dir, "references.parquet")

    papers_out = os.path.join(export_dir, "papers.parquet")
    refs_out = os.path.join(export_dir, "references.parquet")

    # Chuyển đổi bảng papers
    if os.path.exists(pub_in):
        working_pubs = pq.read_table(pub_in).to_pylist()
    else:
        working_pubs = []

    course_papers: list[dict] = []
    for p in working_pubs:
        arxiv_id = p["id"]
        title = p["title"]
        authors = p["authors"] or []
        venue = p["venue"]

        versions = p.get("versions") or []
        if versions:
            versions = sorted(versions, key=lambda x: _parse_version_num(x.get("version")))

        published_dt = p.get("published")
        updated_dt = p.get("updated")

        published_iso = published_dt.isoformat() if isinstance(published_dt, datetime) else None
        updated_iso = updated_dt.isoformat() if isinstance(updated_dt, datetime) else None

        # Tính submission_date
        sub_date = None
        if versions and versions[0].get("created"):
            c = versions[0]["created"]
            sub_date = c.isoformat() if isinstance(c, datetime) else str(c)
        if not sub_date:
            sub_date = published_iso

        # Tính revised_dates
        revised_dates: list[str] = []
        if len(versions) >= 2:
            raw_revised = []
            for v in versions[1:]:
                c = v.get("created")
                d_str = c.isoformat() if isinstance(c, datetime) else (str(c) if c else None)
                if d_str:
                    raw_revised.append(d_str)
            # Khử trùng lặp và sắp xếp tăng dần
            revised_dates = sorted(set(raw_revised))
        else:
            revised_dates = []

        course_papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors,
            "submission_date": sub_date,
            "revised_dates": revised_dates,
            "venue": venue,
        })

    if course_papers:
        papers_table = pa.Table.from_pylist(course_papers, schema=COURSE_PAPERS_SCHEMA)
    else:
        papers_table = COURSE_PAPERS_SCHEMA.empty_table()
    _write_parquet_atomic(papers_table, papers_out, compression="snappy")

    # Chuyển đổi bảng references
    if os.path.exists(ref_in):
        working_refs = pq.read_table(ref_in).to_pylist()
    else:
        working_refs = []

    seen_pairs: set[tuple[str, str]] = set()
    course_refs: list[dict] = []

    for r in working_refs:
        ref_arxiv_id = r.get("ref_arxiv_id")
        if not ref_arxiv_id:
            # Course export chỉ giữ target có arXiv ID.
            continue
        arxiv_id = r["arxiv_id"]
        pair_key = (arxiv_id, ref_arxiv_id)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        course_refs.append({
            "arxiv_id": arxiv_id,
            "ref_arxiv_id": ref_arxiv_id,
            "ref_title": r.get("ref_title"),
            "ref_authors": r.get("ref_authors") or [],
            "ref_submission_date": r.get("ref_submission_date"),
            "ref_s2_id": r.get("ref_s2_id"),
        })

    if course_refs:
        refs_table = pa.Table.from_pylist(course_refs, schema=COURSE_REFERENCES_SCHEMA)
    else:
        refs_table = COURSE_REFERENCES_SCHEMA.empty_table()
    _write_parquet_atomic(refs_table, refs_out, compression="snappy")

    return papers_out, refs_out
