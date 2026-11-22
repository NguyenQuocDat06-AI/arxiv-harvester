"""CLI thu thập metadata, nguồn và trích dẫn; hỗ trợ resume và đo tài nguyên.

Phụ trách: Trịnh Vỹ Triết (24120474).
"""

import argparse
import concurrent.futures
import contextlib
import json
import logging
import os
import re
import sys
import time
import uuid
import math
import hashlib
from copy import deepcopy
from collections import deque
from .pipeline_support import BoundedExecutor
from .reference_retry import ReferenceRetryQueue
from .reference_state import needs_individual, preserve_evidence, retry_remaining
from datetime import datetime, timezone
from pathlib import Path
from itertools import islice
from typing import Any, Iterable, Iterator

from .discovery import discover_metadata_batch
from .id_range import iter_assigned_arxiv_ids
from .profiler import ResourceProfiler
from .reference_scraper import ReferenceResult, scrape_references_for_paper, get_request_stats, configure_request_policy, reset_request_stats, reference_cooldown_remaining
from .reference_batch import scrape_references_batch, complete_batch_result
from .records import base_id, merge_publications, merge_references, sources_complete, tex_complete, REFERENCE_TERMINAL, REFERENCE_REPLACE, SOURCE_TERMINAL
from .observations import save_observations, request_delta, combine_request_metrics
from .profiler import _write_json_atomic
from .source_downloader import download_and_clean_source, download_and_extract_source, extract_and_clean_archive
from .validate_sources import check_source_version
from .rate_limiter import rate_limiter
from .request_policy import network_runtime, CooldownDeferred
from .exceptions import arXivRateLimitError
from .reference_scraper import _api_headers
from .storage import (
    export_to_course_spec,
    resolve_paper_source_status,
    save_publications_parquet,
    save_references_parquet,
)

logger = logging.getLogger("crawler")

CHECKPOINT_DIRNAME = "_checkpoint"
STATE_FILENAME = "state.json"
_MONTH_RE = re.compile(r"^(?:(\d{4})-(\d{2})|(\d{2})(\d{2}))$")
_VERSION_RE = re.compile(r"v\d+$")


class ConfigError(Exception):
    """Lỗi cấu hình buộc dừng pipeline."""


def _month_key(value: str) -> tuple[int, int]:
    """Chuyển YYYY-MM hoặc YYMM thành (năm, tháng)."""
    match = _MONTH_RE.match(value.strip())
    if not match:
        raise ValueError(f"tháng '{value}' phải có dạng YYYY-MM hoặc YYMM")
    if match.group(1):
        year, month = int(match.group(1)), int(match.group(2))
    else:
        year, month = 2000 + int(match.group(3)), int(match.group(4))
    if not 1 <= month <= 12:
        raise ValueError(f"tháng '{value}' không hợp lệ")
    if year < 2007:
        raise ValueError(f"tháng '{value}' trước 2007, không dùng định dạng YYMM.NNNNN")
    return year, month


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' không phải số nguyên") from None
    if number <= 0:
        raise argparse.ArgumentTypeError(f"'{value}' phải là số nguyên dương")
    return number


def _non_negative_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' không phải số thực") from None
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError(f"'{value}' không được âm")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.crawler.main",
        description="Thu thập metadata, mã nguồn và trích dẫn arXiv cho khoảng ID được giao.",
    )
    parser.add_argument("--member-id", required=True, help="MSSV 8 chữ số, ví dụ 24120474")
    parser.add_argument("--start-month", required=True, help="Tháng bắt đầu, YYYY-MM hoặc YYMM")
    parser.add_argument("--start-id", required=True, type=_positive_int, help="Số thứ tự đầu (tính cả)")
    parser.add_argument("--end-month", required=True, help="Tháng kết thúc, YYYY-MM hoặc YYMM")
    parser.add_argument("--end-id", required=True, type=_positive_int, help="Số thứ tự cuối (tính cả)")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Thư mục phân vùng cá nhân (mặc định: data/shards/<member-id>)",
    )
    parser.add_argument("--raw-dir", default="data/raw", help="Thư mục dữ liệu thô (mặc định: data/raw)")
    parser.add_argument("--batch-size", type=_positive_int, default=50, help="Số ID mỗi lô (mặc định: 50)")
    parser.add_argument(
        "--rate-limit-sec",
        type=_non_negative_float,
        default=3.0,
        help="Khoảng nghỉ API metadata, giây (tối thiểu 3.0)",
    )
    parser.add_argument(
        "--profile-interval-sec",
        type=_non_negative_float,
        default=0.5,
        help="Chu kỳ lấy mẫu RSS, giây (mặc định: 0.5)",
    )
    parser.add_argument("--s2-rate-limit-sec", type=_non_negative_float, default=5.0,
                        help="Khoảng nghỉ S2, độc lập với arXiv (mặc định: 5 giây)")
    parser.add_argument("--s2-background-retries", type=int, default=6,
                        help="Số lần retry nền S2 mỗi bài trong lúc tải nguồn; 0 để tắt, tối đa 20")
    parser.add_argument("--disk-profile-interval-sec", type=_non_negative_float, default=30.0,
                        help="Chu kỳ quét dung lượng đĩa, giây (mặc định 30)")
    parser.add_argument("--s2-batch-size", type=_positive_int, default=50,
                        help="Số paper/request S2, tối đa 500; đặt 1 để gọi riêng")
    parser.add_argument("--rate-state-dir", help="Thư mục lưu cooldown dùng chung qua các lượt chạy")
    parser.add_argument("--max-rate-wait-sec", type=_non_negative_float, default=180.0,
                        help="Khoảng chờ inline tối đa; lâu hơn thì lưu checkpoint và tạm dừng")
    parser.add_argument("--auto-resume-rate-limit", action="store_true",
                        help="Lưu checkpoint, chờ cooldown arXiv rồi tự tiếp tục; có thể Stop khi đang chờ")
    parser.add_argument("--recheck-missing", action="store_true",
                        help="Kiểm tra lại các ID đã đánh dấu missing trong phạm vi lượt chạy")
    parser.add_argument("--recheck-bib-fallback", action="store_true",
                        help="Kiểm tra lại S2 cho Bib fallback cũ khi resume, giữ nguồn đã xác minh")
    parser.add_argument("--checkpoint-every-papers", type=_positive_int, default=25,
                        help="Lưu checkpoint sau số paper này, độc lập với batch API")
    parser.add_argument("--max-inflight-papers", type=_positive_int, default=25,
                        help="So paper toi da dang cho xu ly nen (mac dinh 25)")
    parser.add_argument("--s2-max-attempts", type=_positive_int, default=3,
                        help="Số lần thử S2 trong một lượt (mặc định: 3)")
    parser.add_argument("--s2-cooldown-sec", type=_non_negative_float, default=60.0,
                        help="Thời gian nghỉ S2 sau khi hết lượt HTTP 429")
    parser.add_argument("--s2-recovery-passes", type=int, default=2,
                        help="Số lượt lấy bù khi --s2-drain-budget-sec=0 (0–5, mặc định 2)")
    parser.add_argument("--s2-drain-budget-sec", type=_non_negative_float, default=10800.0,
                        help="Ngân sách lấy bù references cuối lượt; mặc định 3 giờ, 0 dùng giới hạn số vòng cũ")
    parser.add_argument("--s2-incomplete-recheck-sec", type=_non_negative_float, default=21600.0,
                        help="Hẹn kiểm tra lại sau khi S2 đã hết trang nhưng vẫn thiếu; mặc định 6 giờ")
    parser.add_argument("--run-budget-sec", type=_non_negative_float, default=41400.0,
                        help="Ngân sách toàn lượt trước khi lưu checkpoint; mặc định 11,5 giờ")
    parser.add_argument("--s2-recovery-max-wait-sec", type=_non_negative_float, default=1200.0,
                        help="Chờ cooldown trước mỗi lượt lấy bù S2, tối đa 1200 giây mặc định")
    parser.add_argument("--source-download-attempts", type=_positive_int, default=3,
                        help="Số lần tải một version trong mỗi lượt (mặc định: 3)")
    parser.add_argument("--source-rate-limit-sec", type=_non_negative_float, default=3.0,
                        help="Khoảng nghỉ tải full-text, tối thiểu 3 giây theo đề")
    parser.add_argument("--backup-dir", help="Nơi lưu archive checkpoint theo lô, ví dụ thư mục Drive")
    parser.add_argument("--backup-every-papers", type=_positive_int, default=10,
                        help="Số paper giữa hai lần backup đã xác minh (mặc định 10)")
    parser.add_argument("--source-read-timeout-sec", type=_non_negative_float, default=90.0,
                        help="Timeout khi nguồn không truyền thêm dữ liệu, giây")
    parser.add_argument("--source-max-seconds", type=_non_negative_float, default=180.0,
                        help="Ngân sách tải mỗi version; hết thời gian giữ .part để resume")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Tiếp tục từ checkpoint, bỏ qua các bài đã hoàn thành",
    )
    parser.add_argument("--existing-only", action="store_true", help="Chỉ sửa các bài đã có trong checkpoint")
    parser.add_argument("--run-id", help="Mã run dùng chung với notebook")
    parser.add_argument(
        "--max-papers",
        type=_positive_int,
        default=None,
        help="Giới hạn số bài tối đa cần xử lý (hữu ích cho smoke test và gỡ lỗi)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chạy thử nghiệm khám phá metadata mà không tải tệp nguồn hoặc gọi Semantic Scholar thật",
    )
    parser.add_argument(
        "--export-course",
        action="store_true",
        help="Tự động xuất papers.parquet và references.parquet theo chuẩn đề bài 6+6 cột sau khi hoàn tất",
    )
    parser.add_argument(
        "--course-export-dir",
        default=None,
        help="Thư mục xuất chuẩn môn học (mặc định: <output-dir>/course_export)",
    )
    parser.add_argument(
        "--source-endpoint",
        choices=["src", "e-print"],
        default="src",
        help="Endpoint tải source từ export.arxiv.org (mặc định: src; tùy chọn: e-print)",
    )
    parser.add_argument(
        "--open-ended-range",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Tải phần còn lại của file resume trong 1 request không giới hạn range segment (mặc định: True)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Nhận MSSV, bốn mốc ID, thư mục đầu ra và các tùy chọn chạy."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not re.fullmatch(r"\d{8}", args.member_id):
        parser.error("--member-id phải gồm đúng 8 chữ số")
    try:
        start_key = _month_key(args.start_month)
        end_key = _month_key(args.end_month)
    except ValueError as exc:
        parser.error(str(exc))
    for name in ("start_id", "end_id"):
        if getattr(args, name) > 99999:
            parser.error(f"--{name.replace('_', '-')} vượt quá 5 chữ số")
    if (start_key, args.start_id) > (end_key, args.end_id):
        parser.error("mốc bắt đầu phải đứng trước hoặc trùng mốc kết thúc")
    if args.profile_interval_sec == 0:
        parser.error("--profile-interval-sec phải lớn hơn 0")
    if args.disk_profile_interval_sec == 0:
        parser.error("--disk-profile-interval-sec phải lớn hơn 0")
    if args.rate_limit_sec < 3 or args.source_rate_limit_sec < 3:
        parser.error("Metadata và tải nguồn cần >= 3 giây theo đề")
    if args.s2_rate_limit_sec < 1 or min(args.source_read_timeout_sec, args.source_max_seconds, args.max_rate_wait_sec) <= 0:
        parser.error("--s2-rate-limit-sec phải >= 1; timeout/ngân sách tải nguồn phải > 0")
    if args.s2_batch_size > 500:
        parser.error("--s2-batch-size không vượt quá 500")
    if not 0 <= args.s2_background_retries <= 20:
        parser.error("--s2-background-retries phải từ 0 đến 20")
    if args.run_budget_sec <= 0:
        parser.error("--run-budget-sec phải lớn hơn 0")
    if args.s2_incomplete_recheck_sec <= 0:
        parser.error("--s2-incomplete-recheck-sec phải lớn hơn 0")
    if not 0 <= args.s2_recovery_passes <= 5:
        parser.error("--s2-recovery-passes phải từ 0 đến 5")
    if args.existing_only and not args.resume:
        parser.error("--existing-only cần --resume")
    if args.recheck_bib_fallback and not args.resume:
        parser.error("--recheck-bib-fallback cần --resume")
    if args.run_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run_id):
        parser.error("--run-id chỉ nhận chữ, số, dấu gạch ngang và gạch dưới")

    args.start_month = f"{start_key[0]:04d}-{start_key[1]:02d}"
    args.end_month = f"{end_key[0]:04d}-{end_key[1]:02d}"
    if args.output_dir is None:
        args.output_dir = os.path.join("data", "shards", args.member_id)
    if os.path.exists(args.output_dir) and not os.path.isdir(args.output_dir):
        parser.error(f"--output-dir '{args.output_dir}' không phải thư mục")
    return args


def _batched(items: Iterable[str], size: int) -> Iterator[list[str]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _record_id(record: dict) -> str | None:
    value = record.get("id") or record.get("arxiv_id")
    return _VERSION_RE.sub("", str(value)) if value else None


def _id_range(args: argparse.Namespace) -> dict:
    return {
        "start_month": args.start_month,
        "start_id": args.start_id,
        "end_month": args.end_month,
        "end_id": args.end_id,
    }


class Checkpoint:
    """Atomic batch journal retaining records across revisions."""

    def __init__(self, output_dir: str) -> None:
        self.dir = os.path.join(output_dir, CHECKPOINT_DIRNAME)
        self.path = os.path.join(self.dir, STATE_FILENAME)
        self.state: dict = {}

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def init_new(self, member_id: str, id_range: dict) -> None:
        self.state = {"schema_version": 2, "member_id": member_id, "id_range": id_range,
                      "next_batch": 1, "parts": {"publications": [], "references": [], "statuses": []},
                      "done_ids": [], "confirmed_missing": [], "paper_states": {}, "failed": {}, "counts": {}}
        os.makedirs(self.dir, exist_ok=True)
        self.save()

    def load(self, member_id: str, id_range: dict, backup_legacy: bool = True) -> None:
        with open(self.path, encoding="utf-8") as stream:
            self.state = json.load(stream)
        if self.state.get("member_id") != member_id or self.state.get("id_range") != id_range:
            raise ConfigError("Checkpoint thuộc MSSV/khoảng ID khác; kiểm tra tham số và --output-dir")
        if backup_legacy and self.state.get("schema_version", 1) < 2:
            digest = hashlib.sha256(Path(self.path).read_bytes()).hexdigest()[:16]
            backup = Path(self.dir) / "legacy_backups" / f"state_{digest}.json"
            if not backup.exists():
                _write_json_atomic(str(backup), self.state)
        for kind in ("publications", "references", "statuses"):
            names = self.state.setdefault("parts", {}).setdefault(kind, [])
            if not isinstance(names, list):
                raise ConfigError("Danh sách part trong checkpoint không hợp lệ")
            for name in names:
                self.part_path(name)
                if not os.path.isfile(self.part_path(name)):
                    raise ConfigError(f"Checkpoint thiếu part {name}")
        self.state.setdefault("failed", {})
        self.state.setdefault("paper_states", {})
        self.state.setdefault("done_ids", [])
        # Only journaled batches count as complete.

    def save(self) -> None:
        _write_json_atomic(self.path, self.state)

    def part_path(self, name: str) -> str:
        if not isinstance(name, str) or os.path.basename(name) != name or "/" in name or "\\" in name or not name.endswith(".parquet"):
            raise ConfigError("Tên part không hợp lệ")
        return os.path.join(self.dir, name)


def _read_parts(checkpoint: Checkpoint, kind: str) -> list[dict]:
    import pyarrow.parquet as pq
    return [row for name in checkpoint.state["parts"].get(kind, [])
            for row in pq.ParquetFile(checkpoint.part_path(name)).read().to_pylist()]


def _materialize(checkpoint: Checkpoint) -> tuple[dict, dict, dict]:
    import pyarrow.parquet as pq
    publications, references, observations = {}, {}, {}
    events = {}
    for kind, names in checkpoint.state["parts"].items():
        if kind not in ("publications", "references", "statuses"):
            continue
        for name in names:
            match = re.search(r"_(\d+)\.parquet$", name)
            if not match:
                raise ConfigError(f"Tên batch không hợp lệ: {name}")
            events.setdefault(int(match.group(1)), {})[kind] = name
    for batch in sorted(events):
        event = events[batch]
        def read(kind):
            return pq.ParquetFile(checkpoint.part_path(event[kind])).read().to_pylist() if kind in event else []
        for row in read("publications"):
            paper_id = base_id(row)
            publications[paper_id] = merge_publications(publications.get(paper_id), row)
        for row in read("statuses"):
            paper_id = row["arxiv_id"]
            observations[paper_id] = row
            if row.get("reference_update") == "replace":
                references[paper_id] = []
        for row in read("references"):
            paper_id = base_id(row)
            references.setdefault(paper_id, []).append(row)
    references = {key: merge_references(value) for key, value in references.items()}
    return publications, references, observations


def _version_reusable(paper_id: str, version: dict, unzipped_dir: str,
                      session_cache: dict | None = None) -> bool:
    v_tag = str(version.get("version") or "")
    if not re.fullmatch(r"v[1-9]\d*", v_tag):
        return False
    if session_cache is not None:
        verified_set = session_cache.setdefault("verified_reusable", set())
        if (paper_id, v_tag) in verified_set and version.get("source_status") in SOURCE_TERMINAL:
            return True
    verified = check_source_version(Path(unzipped_dir).parent, paper_id, version)["verified"]
    if verified and session_cache is not None:
        session_cache.setdefault("verified_reusable", set()).add((paper_id, v_tag))
    return verified


def _download_paper_sources(arxiv_id: str, args: argparse.Namespace, profiler: ResourceProfiler,
                            sources_dir: str, unzipped_dir: str,
                            paper_record: dict | None = None) -> tuple[dict, dict]:
    paper = paper_record if paper_record is not None else {"id": arxiv_id}
    dry_run = getattr(args, "dry_run", False)
    versions = paper.get("versions") or []
    if not versions:
        raise ValueError(f"Thiếu thông tin version của {arxiv_id}; cần xác minh metadata")
    paper["id"] = arxiv_id
    summary = {"arxiv_id": arxiv_id, "version_results": [], "versions_attempted": 0, "versions_reused": 0}
    session_cache = getattr(args, "_session_cache", None)
    extract_executor = getattr(args, "_extract_executor", None)
    for version in versions:
        tag = version.get("version") or ""
        if not re.fullmatch(r"v[1-9]\d*", tag):
            raise ValueError(f"Version không hợp lệ: {tag!r}")
        if dry_run:
            version["source_status"] = "pending"
            continue
        if _version_reusable(arxiv_id, version, unzipped_dir, session_cache=session_cache):
            summary["versions_reused"] += 1
            continue
        summary["versions_attempted"] += 1
        try:
            with profiler.phase("download_clean"):
                try:
                    result = download_and_clean_source(
                        arxiv_id + tag,
                        sources_dir,
                        unzipped_dir,
                        rate_limit_sec=getattr(args, "source_rate_limit_sec", 3.0),
                        max_attempts=getattr(args, "source_download_attempts", 3),
                        read_timeout_sec=getattr(args, "source_read_timeout_sec", 90.0),
                        max_elapsed_sec=getattr(args, "source_max_seconds", 180.0),
                        open_ended_range=getattr(args, "open_ended_range", True),
                        source_endpoint=getattr(args, "source_endpoint", "src") or "src",
                        allow_defer_heavy=getattr(args, "allow_defer_heavy", True),
                        executor=extract_executor,
                        async_extract=bool(extract_executor is not None),
                        expected_doi=paper.get("doi"),
                    )
                except TypeError as type_err:
                    err_msg = str(type_err)
                    if any(k in err_msg for k in ("source_endpoint", "allow_defer_heavy", "executor", "async_extract", "open_ended_range", "expected_doi")):
                        result = download_and_clean_source(
                            arxiv_id + tag,
                            sources_dir,
                            unzipped_dir,
                            rate_limit_sec=getattr(args, "source_rate_limit_sec", 3.0),
                            max_attempts=getattr(args, "source_download_attempts", 3),
                            read_timeout_sec=getattr(args, "source_read_timeout_sec", 90.0),
                            max_elapsed_sec=getattr(args, "source_max_seconds", 180.0),
                        )
                    else:
                        raise
        except NotImplementedError:
            raise
        except Exception as error:
            result = {"status": "error", "error_message": repr(error)}
        status = result.get("status")
        if result.get("network_metrics") and getattr(args, "_run_dir", None):
            with (Path(args._run_dir) / "source_metrics.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"version_id": arxiv_id+tag, "status": status,
                                         "run_id": args._run_id, **result["network_metrics"]})+"\n")
        if status == "extracting":
            version["_extract_future"] = result.get("_extract_future")
            version["source_status"] = "extracting"
        else:
            version["source_status"] = "success" if status == "ok" else status or "error"
            if version["source_status"] in SOURCE_TERMINAL and session_cache is not None:
                session_cache.setdefault("verified_reusable", set()).add((arxiv_id, tag))
        for field in ("size_before_bytes", "size_after_bytes"):
            if result.get(field) is not None:
                version[field] = result[field]
        summary["version_results"].append(result)
        if result.get("deferred_heavy"):
            summary["deferred_heavy"] = True
            logger.info("Hoãn paper %s (version %s dung lượng >= 30 MiB bị gián đoạn nhiều lần)", arxiv_id, tag)
            break
        if result.get("rate_limited"):
            summary["rate_limited"] = True
            summary["retry_after_sec"] = result.get("retry_after_sec")
            break
    paper["versions"] = versions
    paper.update({"source_status": resolve_paper_source_status([v.get("source_status") for v in versions])})
    for field in ("size_before_bytes", "size_after_bytes"):
        values = [v[field] for v in versions if v.get(field) is not None]
        paper[field] = sum(values) if values else None
    summary.update({"status": paper["source_status"], "size_before_bytes": paper["size_before_bytes"],
                    "size_after_bytes": paper["size_after_bytes"]})
    return summary, paper


def _finalize_paper_extractions(download: dict, paper_meta: dict, unzipped_dir: str,
                                session_cache: dict | None = None, profiler: ResourceProfiler | None = None) -> None:
    arxiv_id = paper_meta.get("id") or paper_meta.get("arxiv_id", "")
    versions = paper_meta.get("versions") or []
    has_extracting = False
    for v in versions:
        fut = v.pop("_extract_future", None)
        if fut is not None:
            has_extracting = True
            phase_ctx = profiler.phase("extraction_wait") if profiler is not None else contextlib.nullcontext()
            try:
                with phase_ctx:
                    final_res = fut.result()
            except Exception as exc:
                final_res = {
                    "arxiv_id": arxiv_id,
                    "version_id": f"{arxiv_id}{v.get('version')}",
                    "status": "error",
                    "error_message": repr(exc),
                    "size_before_bytes": 0,
                    "size_after_bytes": 0,
                }
            st = final_res.get("status")
            v["source_status"] = "success" if st == "ok" else st or "error"
            for field in ("size_before_bytes", "size_after_bytes"):
                if final_res.get(field) is not None:
                    v[field] = final_res[field]
            v_tag = str(v.get("version") or "")
            for res_idx, r in enumerate(download.get("version_results", [])):
                if r.get("_extract_future") is fut or r.get("version_id") == f"{arxiv_id}{v_tag}":
                    download["version_results"][res_idx] = final_res
                    break
            if final_res.get("status") in SOURCE_TERMINAL and session_cache is not None:
                session_cache.setdefault("verified_reusable", set()).add((arxiv_id, v_tag))

    if has_extracting:
        paper_meta["source_status"] = resolve_paper_source_status([v.get("source_status") for v in versions])
        for field in ("size_before_bytes", "size_after_bytes"):
            values = [v[field] for v in versions if v.get(field) is not None]
            paper_meta[field] = sum(values) if values else None
        download.update({
            "status": paper_meta["source_status"],
            "size_before_bytes": paper_meta.get("size_before_bytes"),
            "size_after_bytes": paper_meta.get("size_after_bytes"),
        })


def _resolve_paper_references(arxiv_id: str, args: argparse.Namespace, profiler: ResourceProfiler,
                              unzipped_dir: str, previous_references: list | None = None,
                              previous_observation: dict | None = None,
                              prefetched_references: ReferenceResult | None = None) -> tuple[dict, list[dict]]:
    dry_run = getattr(args, "dry_run", False)
    old = previous_observation or {}
    if dry_run:
        references = []
        observation = {"arxiv_id": arxiv_id, "reference_status": "dry_run", "reference_update": "keep"}
    elif old.get("reference_status") in REFERENCE_TERMINAL:
        references = previous_references or []
        observation = {**old, "reference_update": "keep"}
    elif _run_time_left(args) <= 0 or retry_remaining(old) > 0:
        references = previous_references or []
        observation = {**old, "arxiv_id": arxiv_id, "reference_status": old.get("reference_status", "pending"),
                       "reference_update": "keep", "error_message": old.get("error_message") or "Run time budget reached"}
    else:
        before = get_request_stats()
        try:
            with profiler.phase("references"):
                local = os.path.join(unzipped_dir, arxiv_id.replace("/", "_"))
                interval = getattr(args, "s2_rate_limit_sec", 5.0)
                if (prefetched_references is None and old.get("reference_status") == "partial"
                        and old.get("reference_source") == "semantic_scholar"
                        and isinstance(old.get("expected_count"), int)
                        and not old.get("pagination_exhausted")):
                    prefetched_references = ReferenceResult(
                        [row for row in previous_references or [] if row.get("source") == "semantic_scholar"],
                        status="partial", expected_count=old["expected_count"], raw_count=old.get("raw_count"))
                if prefetched_references is None:
                    references = scrape_references_for_paper(arxiv_id, local, rate_limit_sec=interval)
                else:
                    references = complete_batch_result(arxiv_id, prefetched_references, local, interval)
        except NotImplementedError:
            raise
        except Exception as error:
            references = ReferenceResult([], status="api_error", error_message=repr(error))
        status = getattr(references, "status", "success")
        observation = {"arxiv_id": arxiv_id, "reference_status": status,
                       "reference_source": getattr(references, "source", "legacy"),
                       "expected_count": getattr(references, "expected_count", len(references)),
                       "received_count": len(references), "error_message": getattr(references, "error_message", None),
                       "updated_at": datetime.now(timezone.utc).isoformat(),
                       "reference_update": "replace" if status in REFERENCE_REPLACE else "merge",
                       "raw_count": getattr(references, "raw_count", None),
                       "pagination_exhausted": getattr(references, "pagination_exhausted", False),
                       "lookup_required": getattr(references, "lookup_required", False),
                       "provider_data_error": getattr(references, "provider_data_error", False),
                       "request_group": getattr(prefetched_references, "request_group", None),
                       "request_group_size": getattr(prefetched_references, "request_group_size", 1),
                       **combine_request_metrics(getattr(prefetched_references, "request_metrics", None) or {},
                                                 request_delta(before, get_request_stats()))}
        if status == "not_indexed":
            observation["expected_count"] = None
        observation = preserve_evidence(old, observation, getattr(args, "s2_incomplete_recheck_sec", 21600.0))
        if getattr(args, "_run_dir", None):
            with (Path(args._run_dir) / "reference_attempts.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(observation, ensure_ascii=False) + "\n")
    return observation, list(references)


def _process_paper(arxiv_id: str, args: argparse.Namespace, profiler: ResourceProfiler,
                   sources_dir: str, unzipped_dir: str, paper_record: dict | None = None,
                   previous_references: list | None = None, previous_observation: dict | None = None,
                   prefetched_references: ReferenceResult | None = None) -> tuple[dict, list[dict]]:
    summary, paper = _download_paper_sources(arxiv_id, args, profiler, sources_dir, unzipped_dir, paper_record)
    _finalize_paper_extractions(summary, paper, unzipped_dir, session_cache=getattr(args, "_session_cache", None), profiler=profiler)
    obs, refs = _resolve_paper_references(arxiv_id, args, profiler, unzipped_dir,
                                          previous_references, previous_observation, prefetched_references)
    if not sources_complete(paper) and obs.get("reference_status") == "not_indexed":
        obs["reference_status"] = "api_error"
    summary["observation"] = obs
    return summary, refs


def _summary(publications: dict, references: dict, observations: dict, missing: set, errors: dict) -> dict:
    completed = {key for key, paper in publications.items()
                 if sources_complete(paper) and observations.get(key, {}).get("reference_status") in REFERENCE_TERMINAL}
    failed = dict(errors)
    for key, paper in publications.items():
        if key not in completed:
            failed[key] = f"source={paper.get('source_status')}; references={observations.get(key, {}).get('reference_status', 'unknown')}"
        else:
            failed.pop(key, None)
    return {"succeeded": len(completed), "source_succeeded": sum(tex_complete(p) for p in publications.values()),
            "sources_verified": sum(sources_complete(p) for p in publications.values()),
            "publications": len(publications), "references": sum(len(r) for r in references.values()),
            "not_found": len(missing), "failed": len(failed), "failed_ids": dict(sorted(failed.items())),
            "source_size_before_bytes": sum(p.get("size_before_bytes") or 0 for p in publications.values()),
            "source_size_after_bytes": sum(p.get("size_after_bytes") or 0 for p in publications.values()),
            "versions_succeeded": sum(v.get("source_status") == "success" for p in publications.values() for v in p.get("versions", []))}


def run_pipeline(args: argparse.Namespace, profiler: ResourceProfiler, checkpoint: Checkpoint,
                 session_cache: dict | None = None, policy: Any = None, extra: dict | None = None) -> dict:
    pipeline_started = time.perf_counter()
    policy = policy or rate_limiter.policy
    extra = extra if extra is not None else getattr(args, "_extra", {})
    args._extra = extra
    cache = session_cache if session_cache is not None else {}
    for name in ("discovered_found", "prefetched_refs"):
        cache.setdefault(name, {})
    cache.setdefault("discovered_absent", set())
    args._session_cache = cache
    if cache.get("materialized_batch") == checkpoint.state.get("next_batch") and cache.get("materialized") is not None:
        publications, references, observations = cache["materialized"]
    else:
        publications, references, observations = _materialize(checkpoint)
    cache["materialized"] = publications, references, observations
    cache["materialized_batch"] = checkpoint.state.get("next_batch")
    missing = set(checkpoint.state.get("confirmed_missing", []))
    errors = dict(checkpoint.state.get("failed", {}))
    sources_dir, unzipped_dir = (os.path.join(args.raw_dir, name) for name in ("sources", "unzipped"))
    os.makedirs(sources_dir, exist_ok=True)
    os.makedirs(unzipped_dir, exist_ok=True)
    with profiler.phase("id_generation"):
        if not hasattr(args, "_assigned_ids"):
            assigned = sorted(publications) if args.existing_only else list(
                iter_assigned_arxiv_ids(args.start_month, args.start_id, args.end_month, args.end_id))
            args._assigned_ids = assigned[:args.max_papers] if args.max_papers else assigned
        all_ids = args._assigned_ids
    if getattr(args, "recheck_missing", False) and not getattr(args, "_missing_rechecked", False):
        missing.difference_update(all_ids)
        args._missing_rechecked = True
    rechecks = []
    if getattr(args, "recheck_bib_fallback", False) and not getattr(args, "_bib_rechecked", False):
        for key in all_ids:
            old = observations.get(key, {})
            if old.get("reference_status") == "bib_fallback":
                observation = {**old, "reference_status": "bib_pending", "reference_update": "keep",
                               "updated_at": datetime.now(timezone.utc).isoformat(),
                               "error_message": "S2 recheck explicitly requested for previous Bib fallback"}
                observations[key] = observation
                rechecks.append(observation)
                errors[key] = observation["error_message"]
                if getattr(args, "_drive_backup", None):
                    args._backup_dirty_ids.add(key)
        args._bib_rechecked = True
    recovery_ids = getattr(args, "_reference_recovery_ids", None)
    if recovery_ids is not None:
        pending = [key for key in all_ids if key in recovery_ids and key in publications and
                   observations.get(key, {}).get("reference_status") not in REFERENCE_TERMINAL]
    else:
        pending = [key for key in all_ids if key not in missing and (
            key not in publications or not sources_complete(publications[key]) or
            not all(_version_reusable(key, v, unzipped_dir, cache) for v in publications[key].get("versions", [])) or
            observations.get(key, {}).get("reference_status") not in REFERENCE_TERMINAL)]
    pending_at_start = len(pending)
    deferred_s2 = []
    if recovery_ids is None and policy.snapshot("semantic_scholar")["remaining_sec"] > 0:
        deferred_s2 = [key for key in pending if key in publications and
                       sources_complete(publications[key]) and
                       observations.get(key, {}).get("reference_status") in {"api_error", "bib_pending"} and
                       all(_version_reusable(key, v, unzipped_dir, cache) for v in publications[key].get("versions", []))]
        pending = [key for key in pending if key not in set(deferred_s2)]
    deferred = getattr(args, "_rate_deferred_ids", set())
    heavy = getattr(args, "_heavy_deferred_ids", set())
    pending.sort(key=lambda key: (key in deferred, key in heavy,
                 (observations.get(key, {}).get("last_network_attempt_at") or "") if recovery_ids is not None else ""))
    logger.info("Phạm vi %d ID; %d cần xử lý, %d đã đủ hoặc đã xác nhận không tồn tại",
                len(all_ids), len(pending), len(all_ids)-len(pending))
    checkpoint_every = getattr(args, "checkpoint_every_papers", 25)
    max_inflight = 1 if checkpoint_every == 1 else getattr(args, "max_inflight_papers", 25)
    s2_executor = cache.get("s2_executor")
    owns_s2 = s2_executor is None
    if owns_s2:
        s2_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="S2")
    post_executor = BoundedExecutor(max_workers=1, max_pending=max_inflight, thread_name_prefix="PostProcessor")
    extract_executor = BoundedExecutor(max_workers=2, max_pending=4, thread_name_prefix="ArchiveExtractor",
                                       profiler=profiler, phase_name="extract_clean")
    drive_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="DriveBackup")
    args._extract_executor = extract_executor
    drive_future = None
    reference_queue = deque()
    reference_future = None
    reference_items = []
    pending_metrics = {}
    lookup_futures = {}
    lookup_future = None
    background_retry = None
    jobs = deque()
    batch_pubs, batch_refs, batch_status, batch_metrics = [], [], [], []
    batch_status.extend(rechecks)
    metrics = []
    attempted_versions = reused_versions = visited_ids = 0
    last_checkpoint = time.perf_counter()
    metrics_path = Path(args._run_dir)/"paper_metrics.jsonl"
    metrics_path.touch(exist_ok=True)
    failures = []
    extra["paper_metric_scope"] = (
        "Per-paper attempt latency includes queue waits; overlapping latencies are not wall time. "
        "Later background retries are recorded in reference_retry_metrics.jsonl and provider phase timers.")
    extra["s2_background_retry_scope"] = (
        "Retries share the single S2 executor; cooldown waiting overlaps source work. "
        "Scheduler counters do not establish that all references are complete.")
    extra["phase_timing_scope"] = "Worker service intervals may overlap; use runtime_sec or child_wall_sec for end-to-end time."
    extra["pipeline_max_inflight_observed"] = extra.get("pipeline_max_inflight_observed", 0)

    def fetch_references(keys):
        if _run_time_left(args) <= 0:
            return ({key: ReferenceResult([], status="api_error", error_message="Run time budget reached") for key in keys},
                    0.0, len(keys))
        started = time.perf_counter()
        with profiler.phase("s2_batch"):
            result = scrape_references_batch(keys, rate_limit_sec=args.s2_rate_limit_sec, batch_size=args.s2_batch_size)
        return result, time.perf_counter()-started, len(keys)

    def stage_b(key, download, paper, started, source_sec, discovery_sec):
        post_started = time.perf_counter()
        begin = time.perf_counter()
        _finalize_paper_extractions(download, paper, unzipped_dir, session_cache=cache, profiler=profiler)
        extraction_wait = time.perf_counter()-begin
        finished = time.perf_counter()
        metric = {"arxiv_id": key, "run_id": args._run_id, "source_sec": source_sec,
                  "post_queue_sec": max(0.0, post_started-started-source_sec),
                  "extraction_wait_sec": extraction_wait, "reference_wait_sec": 0.0,
                  "compute_sec": source_sec+max(0.0, finished-post_started-extraction_wait),
                  "latency_sec": finished-started, "elapsed_sec": finished-started,
                  "discovery_allocated_sec": discovery_sec, "reference_batch_allocated_sec": 0.0,
                  "source_ready_sec": finished-started, "_started": started,
                  "versions_attempted": download["versions_attempted"], "versions_reused": download["versions_reused"]}
        return key, paper, download, metric

    def resolve_references(items):
        keys = [key for key, _, old, _ in items if old.get("reference_status") not in REFERENCE_TERMINAL
                and retry_remaining(old) <= 0 and not needs_individual(old)]
        allocation = {}
        lookups = {lookup_futures[key] for key in keys if key in lookup_futures}
        for future in lookups:
            try:
                results, duration, count = future.result()
                cache["prefetched_refs"].update(results)
                allocation.update({key: duration/max(1, count) for key in keys if lookup_futures.get(key) is future})
            except Exception as error:
                cache["prefetched_refs"].update({key: ReferenceResult([], status="api_error", error_message=repr(error))
                                                for key in keys if lookup_futures.get(key) is future})
        if policy.snapshot("semantic_scholar")["remaining_sec"] <= 0:
            for key in keys:
                previous = cache["prefetched_refs"].get(key)
                if previous is not None and previous.status == "api_error":
                    cache["prefetched_refs"].pop(key, None)
        needing = [key for key in keys if key not in cache["prefetched_refs"]]
        if needing and not args.dry_run and args.s2_batch_size > 1:
            try:
                results, duration, count = fetch_references(needing)
                cache["prefetched_refs"].update(results)
                allocation.update({key: duration/max(1, count) for key in needing})
            except Exception as error:
                cache["prefetched_refs"].update({key: ReferenceResult([], status="api_error", error_message=repr(error))
                                                for key in needing})
        result = []
        for key, old_refs, old, paper in items:
            started = time.perf_counter()
            obs, refs = _resolve_paper_references(key, args, profiler, unzipped_dir, old_refs, old,
                                                 cache["prefetched_refs"].get(key))
            if recovery_ids is None and not sources_complete(paper) and obs.get("reference_status") == "not_indexed":
                obs["reference_status"] = "api_error"
            result.append((key, obs, refs, time.perf_counter()-started, allocation.get(key, 0.0),
                           started, time.perf_counter()))
        return result

    def apply_reference_result(key, obs, refs):
        if obs["reference_update"] == "replace":
            references[key] = merge_references(refs)
            # A retry can replace Bib edges before the current part is flushed.
            batch_refs[:] = [row for row in batch_refs if base_id(row) != key]
        elif obs["reference_update"] == "merge":
            references[key] = merge_references([*references.get(key, []), *refs])
        observations[key] = obs
        if obs["reference_update"] != "keep":
            batch_refs.extend(refs)
        batch_status.append(obs)
        if getattr(args, "_drive_backup", None):
            args._backup_dirty_ids.add(key)

    def collect_background_references():
        if background_retry is None:
            return
        for row in background_retry.drain():
            if isinstance(row, BaseException):
                failures.append(row)
                continue
            key, obs, refs = row[:3]
            apply_reference_result(key, obs, refs)
            cache["prefetched_refs"].pop(key, None)
            logger.info("S2 retry nền xong: %s | status=%s, records=%d",
                        key, obs["reference_status"], len(refs))

    def retry_references(items):
        keys = [key for key, _, old, _ in items if retry_remaining(old) <= 0 and not needs_individual(old)]
        results, duration, count = fetch_references(keys) if keys and args.s2_batch_size > 1 else ({}, 0.0, len(keys))
        resolved = []
        for key, old_refs, old, paper in items:
            started = time.perf_counter()
            obs, refs = _resolve_paper_references(key, args, profiler, unzipped_dir,
                                                 old_refs, old, results.get(key))
            if not sources_complete(paper) and obs.get("reference_status") == "not_indexed":
                obs["reference_status"] = "api_error"
            resolved.append((key, obs, refs, time.perf_counter()-started, duration/max(1, count),
                             started, time.perf_counter()))
        return resolved

    def collect_references(wait=False):
        nonlocal reference_future, reference_items
        if reference_future is None or (not wait and not reference_future.done()):
            return
        future, reference_future = reference_future, None
        try:
            resolved = future.result()
        except BaseException as error:
            failures.append(error)
            return
        reference_items = []
        for key, obs, refs, duration, allocated, started, finished in resolved:
            apply_reference_result(key, obs, refs)
            metric = pending_metrics.pop(key)
            metric["reference_wait_sec"] = duration
            metric["reference_batch_allocated_sec"] = allocated
            metric["reference_queue_sec"] = max(0.0, started-metric["_started"]-metric["source_ready_sec"])
            metric["latency_sec"] = metric["elapsed_sec"] = finished-metric.pop("_started")
            batch_metrics.append(metric)
            if background_retry is not None and sources_complete(publications[key]):
                background_retry.add((key, references.get(key), obs, publications[key]))

    def schedule_references(force=False):
        nonlocal reference_future, reference_items
        collect_background_references()
        collect_references()
        if getattr(args, "_paused_time_budget", False):
            return
        target = max(1, args.s2_batch_size)
        if reference_future is not None or not reference_queue or (not force and len(reference_queue) < target):
            return
        reference_items = []
        for _ in range(min(target, len(reference_queue))):
            key = reference_queue.popleft()
            reference_items.append((key, references.get(key), deepcopy(observations.get(key, {})), publications[key]))
        reference_future = s2_executor.submit(resolve_references, reference_items)
        extra["reference_backlog_max"] = max(extra.get("reference_backlog_max", 0), len(reference_queue)+len(reference_items))

    def collect(wait_one=False, wait_all=False):
        nonlocal attempted_versions, reused_versions
        collected = 0
        while jobs:
            if not wait_all and not jobs[0][1].done() and not (wait_one and collected == 0):
                break
            key, future = jobs.popleft()
            try:
                key, paper, download, metric = future.result()
            except BaseException as error:
                errors[key] = repr(error)
                failures.append(error)
                continue
            publications[key] = merge_publications(publications.get(key), paper)
            attempted_versions += download["versions_attempted"]
            reused_versions += download["versions_reused"]
            batch_pubs.append(publications[key])
            pending_metrics[key] = metric
            old = observations.get(key, {})
            if old.get("reference_status") not in REFERENCE_TERMINAL:
                obs = {**old, "arxiv_id": key, "reference_status": old.get("reference_status", "pending"),
                       "reference_update": "keep", "updated_at": datetime.now(timezone.utc).isoformat()}
                observations[key] = obs
                batch_status.append(obs)
            reference_queue.append(key)
            extra["reference_backlog_max"] = max(extra.get("reference_backlog_max", 0), len(reference_queue)+len(reference_items))
            if getattr(args, "_drive_backup", None):
                args._backup_dirty_ids.add(key)
            collected += 1
        schedule_references()

    def flush():
        nonlocal errors, drive_future, last_checkpoint
        if drive_future is not None:
            drive_future.result()
            drive_future = None
        started = time.perf_counter()
        batch_no = checkpoint.state["next_batch"]
        next_state = deepcopy(checkpoint.state)
        with profiler.phase("storage"):
            for kind, rows, writer in (("publications", batch_pubs, save_publications_parquet),
                                       ("references", batch_refs, save_references_parquet),
                                       ("statuses", batch_status, save_observations)):
                if rows:
                    name = f"{kind}_{batch_no:05d}.parquet"
                    writer(rows, checkpoint.part_path(name))
                    next_state["parts"].setdefault(kind, []).append(name)
            current = _summary(publications, references, observations, missing, errors)
            errors = dict(current["failed_ids"])
            next_state.update(schema_version=2, next_batch=batch_no+1, confirmed_missing=sorted(missing),
                              done_ids=sorted(set(publications)|missing), failed=errors, counts=current,
                              paper_states={key: {"sources": {v["version"]: v.get("source_status") for v in p.get("versions", [])},
                                                  "reference_status": observations.get(key, {}).get("reference_status", "unknown")}
                                            for key, p in publications.items()})
            _write_json_atomic(checkpoint.path, next_state)
            checkpoint.state = next_state
            cache["materialized_batch"] = next_state["next_batch"]
        storage_sec = time.perf_counter()-started
        with metrics_path.open("a", encoding="utf-8") as stream:
            for metric in batch_metrics:
                metric["storage_allocated_sec"] = storage_sec/max(1, len(batch_metrics))
                stream.write(json.dumps(metric)+"\n")
                metrics.append(metric)
        backup = getattr(args, "_drive_backup", None)
        if backup:
            args._backup_papers += len({row.get("id") or row.get("arxiv_id") for row in [*batch_pubs, *batch_status]})
            if args._backup_papers >= args.backup_every_papers:
                dirty = set(args._backup_dirty_ids)
                def save_backup():
                    try:
                        with profiler.phase("drive_backup"):
                            backup.save(dirty)
                    except BaseException:
                        args._backup_failed = True
                        raise
                if args.backup_every_papers == 1:
                    save_backup()
                else:
                    drive_future = drive_executor.submit(save_backup)
                args._backup_dirty_ids.clear()
                args._backup_papers = 0
        logger.info("Checkpoint %d: %d nguồn đã xác minh, %d bài hoàn tất, %d bài cần xử lý tiếp",
                    batch_no, current["sources_verified"], current["succeeded"], current["failed"])
        for rows in (batch_pubs, batch_refs, batch_status, batch_metrics):
            rows.clear()
        last_checkpoint = time.perf_counter()

    def maybe_flush():
        collect_background_references()
        if (batch_pubs or batch_status) and (max(len(batch_pubs), len(batch_metrics)) >= checkpoint_every or time.perf_counter()-last_checkpoint >= 30):
            flush()
        if failures:
            raise failures[0]

    background_attempts = getattr(args, "s2_background_retries", 6)
    if background_attempts and not args.dry_run and recovery_ids is None:
        background_retry = ReferenceRetryQueue(
            s2_executor, retry_references,
            lambda: max(reference_cooldown_remaining(), 3600.0 if _run_time_left(args) <= 0 else 0.0),
            args.s2_batch_size, background_attempts, Path(args._run_dir)/"reference_retry_metrics.jsonl",
            attempts=cache.setdefault("s2_background_attempts", {}))
        for key in deferred_s2:
            background_retry.add((key, references.get(key), observations[key], publications[key]))
        background_retry.start()

    try:
        for offset in range(0, len(pending), args.batch_size):
            if _run_time_left(args) <= 0:
                _pause_for_budget(args, extra, _budget_reason(args))
                break
            batch = pending[offset:offset+args.batch_size]
            collect()
            maybe_flush()
            found = {key: deepcopy(publications[key]) for key in batch if key in publications and publications[key].get("versions")}
            window = pending[offset:offset+max(args.batch_size, 100)]
            needed = [key for key in window if not publications.get(key, {}).get("versions") and
                      key not in cache["discovered_found"] and key not in cache["discovered_absent"]]
            discovery_started = time.perf_counter()
            if needed:
                with profiler.phase("discovery"):
                    try:
                        metadata = discover_metadata_batch(needed, rate_limit_sec=args.rate_limit_sec)
                        for record in metadata:
                            key = _record_id(record)
                            cache["discovered_found"][key] = record
                        for key in needed:
                            if key in getattr(metadata, "missing_confirmed", set()):
                                cache["discovered_absent"].add(key)
                            elif key not in cache["discovered_found"]:
                                errors[key] = str(getattr(metadata, "failed_ids", {}).get(key, "ID chưa được xác minh"))
                    except (arXivRateLimitError, CooldownDeferred) as error:
                        args._paused_rate_limit = True
                        args._rate_retry_after = getattr(error, "retry_after", None)
                        errors.update({key: f"discovery: {error!r}" for key in needed})
                    except (KeyboardInterrupt, NotImplementedError):
                        raise
                    except Exception as error:
                        errors.update({key: f"discovery: {error!r}" for key in needed})
            for key in batch:
                if _run_time_left(args) <= 0:
                    _pause_for_budget(args, extra, _budget_reason(args))
                    break
                if key in cache["discovered_found"] and key not in found:
                    found[key] = merge_publications(publications.get(key), cache["discovered_found"][key])
                if key in cache["discovered_absent"]:
                    missing.add(key)
                    errors.pop(key, None)
            discovery_share = (time.perf_counter()-discovery_started)/max(1, len(found))
            needing_refs = [key for key in batch if key in found and
                            observations.get(key, {}).get("reference_status") not in REFERENCE_TERMINAL and
                            retry_remaining(observations.get(key, {})) <= 0 and
                            not needs_individual(observations.get(key, {})) and
                            key not in cache["prefetched_refs"] and key not in lookup_futures]
            if (needing_refs and not args.dry_run and args.s2_batch_size > 1 and
                    _run_time_left(args) > 0 and (lookup_future is None or lookup_future.done())):
                lookup_future = s2_executor.submit(fetch_references, needing_refs)
                lookup_futures.update({key: lookup_future for key in needing_refs})
            for key in batch:
                if _run_time_left(args) <= 0:
                    _pause_for_budget(args, extra, _budget_reason(args))
                    break
                visited_ids += 1
                collect(wait_one=len(jobs) >= max_inflight)
                maybe_flush()
                if drive_future is not None and drive_future.done():
                    drive_future.result()
                if key not in found:
                    continue
                if not found[key].get("versions"):
                    errors[key] = "discovery: thiếu thông tin version"
                    continue
                started = time.perf_counter()
                try:
                    if recovery_ids is not None:
                        download = {"versions_attempted": 0, "versions_reused": 0, "version_results": []}
                        paper = found[key]
                    else:
                        download, paper = _download_paper_sources(key, args, profiler, sources_dir, unzipped_dir, found[key])
                except BaseException:
                    if getattr(args, "_drive_backup", None):
                        args._backup_dirty_ids.add(key)
                    raise
                source_sec = time.perf_counter()-started
                future = post_executor.submit(stage_b, key, download, paper, started, source_sec, discovery_share)
                jobs.append((key, future))
                extra["pipeline_max_inflight_observed"] = max(extra["pipeline_max_inflight_observed"], len(jobs))
                if checkpoint_every == 1:
                    collect(wait_one=True)
                    maybe_flush()
                if download.get("deferred_heavy"):
                    args._heavy_deferred_ids.add(key)
                if download.get("rate_limited"):
                    collect(wait_all=True)
                    flush()
                    args._rate_retry_after = download.get("retry_after_sec")
                    args._rate_deferred_ids.add(key)
                    if not args.auto_resume_rate_limit:
                        args._paused_rate_limit = True
                        args._rate_failed_id = key
                        break
                    _wait_for_arxiv_inplace(args, profiler, policy, retry_after=args._rate_retry_after, extra=extra)
                    extra["auto_rate_limit_resumes"] = extra.get("auto_rate_limit_resumes", 0)+1
                    if policy.snapshot("arxiv").get("consecutive_429", 0) >= 10:
                        args._paused_rate_limit = True
                        break
            collect()
            schedule_references(force=True)
            maybe_flush()
            elapsed = time.perf_counter()-pipeline_started
            remaining = max(0, len(pending)-visited_ids)
            logger.info("Tiến độ tải: %d/%d ID; %d chờ giải nén, %d chờ references; ước tính pha tải còn %.2f giờ",
                        visited_ids, len(pending), len(jobs), len(reference_queue)+len(reference_items),
                        elapsed/max(1, visited_ids)*remaining/3600)
            if args._paused_rate_limit or getattr(args, "_paused_time_budget", False):
                break
    finally:
        active_error = sys.exc_info()[0] is not None
        if jobs:
            logger.info("Chờ %d bài xử lý nền và sao lưu trước khi kết thúc lượt", len(jobs))
        try:
            collect(wait_all=True)
            if not active_error and not getattr(args, "_paused_time_budget", False):
                if batch_pubs or batch_status:
                    flush()
                while reference_future is not None or reference_queue:
                    schedule_references(force=True)
                    collect_references(wait=True)
                    maybe_flush()
            else:
                if not getattr(args, "_backup_failed", False) and (batch_pubs or batch_status):
                    flush()
                if reference_future is None and not getattr(args, "_paused_time_budget", False):
                    schedule_references(force=True)
                collect_references(wait=True)
            if background_retry is not None:
                background_retry.stop()
                collect_background_references()
            for key, metric in pending_metrics.items():
                metric["latency_sec"] = metric["elapsed_sec"] = time.perf_counter()-metric.pop("_started")
                metric["references_pending"] = True
                batch_metrics.append(metric)
            if not getattr(args, "_backup_failed", False) and (batch_pubs or batch_status or batch_metrics or errors != checkpoint.state.get("failed", {}) or missing != set(checkpoint.state.get("confirmed_missing", []))):
                flush()
        finally:
            if background_retry is not None:
                background_retry.stop()
                totals = cache.setdefault("s2_background_totals", {})
                retry_summary = background_retry.summary()
                for name in ("enqueued", "batches", "paper_attempts", "resolved"):
                    totals[name] = totals.get(name, 0)+retry_summary.get(name, 0)
                extra["s2_background_retry"] = {**totals, "pending": retry_summary["pending"],
                                                 "max_attempts_per_paper": background_attempts}
            post_executor.shutdown(wait=True)
            extract_executor.shutdown(wait=True)
            args._extract_executor = None
            try:
                if drive_future is not None:
                    drive_future.result()
            finally:
                drive_executor.shutdown(wait=True)
                if owns_s2:
                    s2_executor.shutdown(wait=True)
        if failures and not active_error:
            raise failures[0]
    if not getattr(args, "_in_rate_resume_loop", False):
        with profiler.phase("storage"):
            save_publications_parquet([publications[key] for key in sorted(publications)], os.path.join(args.output_dir, "publications.parquet"))
            save_references_parquet([row for key in sorted(references) for row in references[key]], os.path.join(args.output_dir, "references.parquet"))
            save_observations([observations[key] for key in sorted(observations)], os.path.join(args.output_dir, "crawl_status.parquet"))
    current = _summary(publications, references, observations, missing, errors)
    current.update(total_ids=len(all_ids), processed_this_run=len(metrics), pending_at_start=pending_at_start,
                   deferred_s2_cooldown=len(deferred_s2), versions_attempted=attempted_versions, versions_reused=reused_versions,
                   avg_paper_sec_this_run=sum(m["elapsed_sec"] for m in metrics)/len(metrics) if metrics else None)
    current["pending_after_run"] = sum(key not in missing and (key not in publications or not sources_complete(publications[key]) or
        observations.get(key, {}).get("reference_status") not in REFERENCE_TERMINAL) for key in all_ids)
    return current



def _run_time_left(args):
    deadline = getattr(args, "_run_deadline", float("inf"))
    if getattr(args, "_reference_recovery_ids", None) is not None:
        deadline = min(deadline, getattr(args, "_s2_drain_deadline", float("inf")))
    return max(0.0, deadline-time.monotonic())


def _budget_reason(args):
    if (getattr(args, "_reference_recovery_ids", None) is not None and
            getattr(args, "_s2_drain_deadline", float("inf")) < getattr(args, "_run_deadline", float("inf"))):
        return "s2_drain_budget_exhausted"
    return "run_budget_exhausted"


def _pause_for_budget(args, extra, reason):
    args._paused_time_budget = True
    extra["stop_reason"] = reason
    logger.info("Dừng theo ngân sách thời gian: %s; giữ checkpoint để resume", reason)


def _wait_for_arxiv_inplace(args, profiler, policy, retry_after: float | None = None, extra: dict | None = None) -> None:
    fallback_deadline = time.monotonic() + (retry_after or getattr(args, "_rate_retry_after", None) or 0.0)
    started = time.monotonic()
    try:
        with profiler.phase("rate_limit_wait"):
            while True:
                if _run_time_left(args) <= 0:
                    _pause_for_budget(args, extra if extra is not None else {}, "run_budget_exhausted")
                    break
                state = policy.snapshot("arxiv")
                remaining = state["remaining_sec"] if state.get("not_before") else max(0.0, fallback_deadline - time.monotonic())
                if remaining <= 0:
                    break
                logger.info("Đang chờ arXiv rate limit %.0fs tại chỗ; hết cooldown sẽ tự tiếp tục...", remaining)
                time.sleep(min(15.0, remaining, _run_time_left(args)))
            try:
                with policy.state("arxiv") as st:
                    st["interval"] = 0.0
                if policy.snapshot("semantic_scholar")["remaining_sec"] <= 0:
                    with policy.state("semantic_scholar") as st:
                        st["interval"] = 0.0
            except Exception:
                pass
    finally:
        wait_dur = max(0.0, time.monotonic() - started)
        if extra is not None:
            extra["auto_rate_limit_wait_sec"] = extra.get("auto_rate_limit_wait_sec", 0.0) + wait_dur


def _wait_for_arxiv(args, profiler, policy, extra):
    backup = getattr(args, "_drive_backup", None)
    if backup and getattr(args, "_backup_dirty_ids", None):
        try:
            with profiler.phase("drive_backup"):
                backup.save(args._backup_dirty_ids, include_outputs=True)
        except BaseException:
            args._backup_failed = True
            raise
        args._backup_dirty_ids.clear()
        args._backup_papers = 0
    fallback_deadline = time.monotonic() + (getattr(args, "_rate_retry_after", None) or 0)
    started = time.monotonic()
    try:
        with profiler.phase("rate_limit_wait"):
            while True:
                if _run_time_left(args) <= 0:
                    _pause_for_budget(args, extra, "run_budget_exhausted")
                    break
                state = policy.snapshot("arxiv")
                remaining = state["remaining_sec"] if state.get("not_before") else max(0, fallback_deadline - time.monotonic())
                if remaining <= 0:
                    break
                logger.info("Full đang chờ arXiv %.0fs; checkpoint đã lưu, hết cooldown sẽ tự tiếp tục. Stop để dừng.", remaining)
                time.sleep(min(15.0, remaining, _run_time_left(args)))
            try:
                with policy.state("arxiv") as st:
                    st["interval"] = 0.0
                if policy.snapshot("semantic_scholar")["remaining_sec"] <= 0:
                    with policy.state("semantic_scholar") as st:
                        st["interval"] = 0.0
            except Exception:
                pass
    finally:
        extra["auto_rate_limit_wait_sec"] += max(0, time.monotonic() - started)


def _prepare_reference_recovery(args, profiler, policy, cache, extra):
    """Drain unfinished references without re-downloading sources."""
    budget = getattr(args, "s2_drain_budget_sec", 10800.0)
    timed = budget > 0
    if args.dry_run or (not timed and extra.get("s2_recovery_passes", 0) >= getattr(args, "s2_recovery_passes", 2)):
        return False
    materialized = cache.get("materialized")
    if materialized is None:
        return False
    publications, _, observations = materialized
    ids = {key for key in getattr(args, "_assigned_ids", []) if key in publications and
           observations.get(key, {}).get("reference_status") in {"pending", "api_error", "bib_pending", "partial", "unavailable"}}
    if not ids:
        return False
    due = {key for key in ids if retry_remaining(observations.get(key, {})) <= 0}
    extra["s2_evidence_deferred_ids"] = sorted(ids - due)
    if due:
        ids = due
    recheck_wait = min(retry_remaining(observations.get(key, {})) for key in ids)
    now = time.monotonic()
    if timed and not hasattr(args, "_s2_drain_started"):
        args._s2_drain_started = now
        args._s2_drain_deadline = now+budget
    deadline = min(getattr(args, "_run_deadline", float("inf")),
                   args._s2_drain_started+budget if timed else float("inf"))
    extra["s2_recovery_mode"] = "time_budget" if timed else "pass_limit"
    remaining = max(reference_cooldown_remaining(), recheck_wait)
    if timed:
        remaining = max(remaining, max(0.0, getattr(args, "_s2_recovery_last", now-30.0)+30.0-now))
        extra["s2_drain_elapsed_sec"] = max(0.0, now-args._s2_drain_started)
    if deadline <= now or (timed and remaining >= deadline-now):
        total_first = getattr(args, "_run_deadline", float("inf")) <= (args._s2_drain_started+budget if timed else float("inf"))
        reason = ("run_budget_exhausted" if total_first else "s2_drain_budget_exhausted") if deadline <= now else (
            "cooldown_exceeds_run_budget" if total_first else "cooldown_exceeds_s2_budget")
        if deadline > now and recheck_wait >= deadline-now:
            reason = "reference_recheck_deferred"
        _pause_for_budget(args, extra, reason)
        extra["s2_recovery_deferred_sec"] = remaining
        return False
    if not timed and remaining > getattr(args, "s2_recovery_max_wait_sec", 1200.0):
        extra["s2_recovery_deferred_sec"] = remaining
        logger.warning("S2 còn nghỉ %.1fs; giữ checkpoint để resume sau", remaining)
        return False
    logger.info("Lấy bù S2 lượt %d cho %d bài; cooldown %.1fs",
                extra.get("s2_recovery_passes", 0)+1, len(ids), remaining)
    with profiler.phase("s2_recovery_wait"):
        started = time.perf_counter()
        try:
            while remaining > 0:
                if time.monotonic() >= deadline:
                    _pause_for_budget(args, extra, "s2_drain_budget_exhausted" if timed else "run_budget_exhausted")
                    return False
                time.sleep(min(1.0, remaining, max(0.0, deadline-time.monotonic())))
                remaining = max(reference_cooldown_remaining(),
                                min(retry_remaining(observations.get(key, {})) for key in ids))
                if timed:
                    remaining = max(remaining, max(0.0, getattr(args, "_s2_recovery_last", time.monotonic()-30.0)+30.0-time.monotonic()))
        finally:
            extra["s2_recovery_wait_sec"] = extra.get("s2_recovery_wait_sec", 0.0) + time.perf_counter()-started
    for key in ids:
        cache["prefetched_refs"].pop(key, None)
    args._reference_recovery_ids = ids
    args._s2_recovery_last = time.monotonic()
    extra["s2_recovery_passes"] = extra.get("s2_recovery_passes", 0)+1
    return True


def _run_with_rate_resume(args, profiler, checkpoint, policy, extra, session_cache: dict | None = None):
    extra.update(auto_rate_limit_resumes=0, auto_rate_limit_wait_sec=0.0, pipeline_passes=0,
                 s2_recovery_passes=0, s2_recovery_wait_sec=0.0)
    first_pending = None
    args._rate_deferred_ids = set()
    if not hasattr(args, "_heavy_deferred_ids") or args._heavy_deferred_ids is None:
        args._heavy_deferred_ids = set()
    if session_cache is None:
        session_cache = {
            "discovered_found": {},
            "discovered_absent": set(),
            "prefetched_refs": {},
        }
    args._in_rate_resume_loop = True
    session_cache.setdefault("s2_executor", concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="S2Prefetcher"))
    try:
        while True:
            args._paused_rate_limit = False
            args._rate_retry_after = None
            args._rate_failed_id = None
            extra["pipeline_passes"] += 1
            try:
                current = run_pipeline(args, profiler, checkpoint, session_cache=session_cache, policy=policy, extra=extra)
                args._reference_recovery_ids = None
            except (arXivRateLimitError, CooldownDeferred) as error:
                if not args.auto_resume_rate_limit:
                    raise
                args._paused_rate_limit = True
                args._rate_retry_after = getattr(error, "retry_after", None)
                extra["last_rate_limit_error"] = str(error)
                current = None
            except BaseException:
                cached_mat = session_cache.get("materialized")
                pubs, refs, observations = cached_mat if cached_mat is not None else _materialize(checkpoint)
                with profiler.phase("storage"):
                    save_publications_parquet([pubs[key] for key in sorted(pubs)], os.path.join(args.output_dir, "publications.parquet"))
                    save_references_parquet([row for key in sorted(refs) for row in refs[key]], os.path.join(args.output_dir, "references.parquet"))
                    save_observations([observations[key] for key in sorted(observations)], os.path.join(args.output_dir, "crawl_status.parquet"))
                state = checkpoint.state
                current = {**extra.get("results", {}), **_summary(pubs, refs, observations,
                           set(state.get("confirmed_missing", [])), state.get("failed", {}))}
                if hasattr(args, "_assigned_ids"):
                    current["total_ids"] = len(args._assigned_ids)
                    current["pending_after_run"] = sum(key not in set(state.get("confirmed_missing", [])) and
                        (key not in pubs or not sources_complete(pubs[key]) or
                         observations.get(key, {}).get("reference_status") not in REFERENCE_TERMINAL) for key in args._assigned_ids)
                extra["results"] = _accumulate_paper_metrics(args, current, first_pending)
                raise
            if current is not None:
                if first_pending is None:
                    first_pending = current["pending_at_start"]
                current = _accumulate_paper_metrics(args, current, first_pending)
                extra["results"] = current
            if getattr(args, "_paused_time_budget", False):
                pubs, refs, observations = session_cache.get("materialized") or _materialize(checkpoint)
                save_publications_parquet([pubs[key] for key in sorted(pubs)], os.path.join(args.output_dir, "publications.parquet"))
                save_references_parquet([row for key in sorted(refs) for row in refs[key]], os.path.join(args.output_dir, "references.parquet"))
                save_observations([observations[key] for key in sorted(observations)], os.path.join(args.output_dir, "crawl_status.parquet"))
                return current
            rate_deferred = getattr(args, "_rate_deferred_ids", set())
            heavy_deferred = getattr(args, "_heavy_deferred_ids", set())
            has_pending_rate = bool(rate_deferred and current and current.get("pending_after_run", 0) > 0)
            has_pending_heavy = bool(heavy_deferred and current and current.get("pending_after_run", 0) > 0)
            max_sweeps = getattr(args, "max_heavy_sweeps", 10)
            if extra.get("heavy_sweep_passes", 0) >= max_sweeps:
                has_pending_heavy = False
            if extra.get("rate_sweep_passes", 0) >= max_sweeps:
                has_pending_rate = False
            if not args.auto_resume_rate_limit or (not args._paused_rate_limit and not has_pending_heavy and not has_pending_rate):
                if _prepare_reference_recovery(args, profiler, policy, session_cache, extra):
                    continue
                cached_mat = session_cache.get("materialized")
                pubs, refs, observations = cached_mat if cached_mat is not None else _materialize(checkpoint)
                with profiler.phase("storage"):
                    save_publications_parquet([pubs[key] for key in sorted(pubs)], os.path.join(args.output_dir, "publications.parquet"))
                    save_references_parquet([row for key in sorted(refs) for row in refs[key]], os.path.join(args.output_dir, "references.parquet"))
                    save_observations([observations[key] for key in sorted(observations)], os.path.join(args.output_dir, "crawl_status.parquet"))
                return current
            if args._rate_failed_id:
                args._rate_deferred_ids.add(args._rate_failed_id)
                logger.info("Hoãn %s về cuối hàng đợi; tiếp tục các ID khác sau cooldown", args._rate_failed_id)
            if args._paused_rate_limit:
                _wait_for_arxiv(args, profiler, policy, extra)
                extra["auto_rate_limit_resumes"] += 1
                logger.info("Tiếp tục toàn dải sau cooldown arXiv, lần %d; giữ các ID đã xong",
                            extra["auto_rate_limit_resumes"])
            elif has_pending_rate:
                extra["rate_sweep_passes"] = extra.get("rate_sweep_passes", 0) + 1
                logger.info("Bắt đầu đợt sweep lần %d cho %d bài báo bị rate limit đã hoãn",
                            extra["rate_sweep_passes"], len(rate_deferred))
                rate_deferred.clear()
            else:
                extra["heavy_sweep_passes"] = extra.get("heavy_sweep_passes", 0) + 1
                logger.info("Bắt đầu đợt sweep lần %d cho %d bài báo dung lượng lớn đã hoãn",
                            extra["heavy_sweep_passes"], len(heavy_deferred))
    finally:
        args._in_rate_resume_loop = False
        if hasattr(args, "_s2_drain_started"):
            extra["s2_drain_elapsed_sec"] = max(0.0, time.monotonic()-args._s2_drain_started)
        s2_exec = session_cache.pop("s2_executor", None)
        if s2_exec is not None:
            s2_exec.shutdown(wait=True)


def _accumulate_paper_metrics(args, current, first_pending):
    path = Path(args._run_dir) / "paper_metrics.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    unique = len({row["arxiv_id"] for row in rows})
    current.update(processed_this_run=unique, paper_attempts_this_run=len(rows), pending_at_start=first_pending,
                   versions_attempted=sum(row["versions_attempted"] for row in rows),
                   versions_reused=sum(row["versions_reused"] for row in rows),
                   avg_paper_sec_this_run=sum(row["elapsed_sec"] for row in rows) / unique if unique else None)
    return current


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    state_dir = args.rate_state_dir or str(Path(args.output_dir) / "_request_state")
    with network_runtime(state_dir, _api_headers().get("x-api-key", ""), args.max_rate_wait_sec) as policy:
        _execute_main(args, policy)


def _execute_main(args, policy):
    configure_request_policy(max_attempts=args.s2_max_attempts, cooldown_sec=args.s2_cooldown_sec)
    reset_request_stats()
    if args.dry_run:
        args.output_dir = os.path.join(args.output_dir, "_dry_run")
    os.makedirs(args.output_dir, exist_ok=True)
    args._run_id = getattr(args, "run_id", None) or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    args._run_dir = os.path.join(args.output_dir, "runs", args._run_id)
    os.makedirs(args._run_dir, exist_ok=False)
    policy.diagnostic_file = Path(args._run_dir) / "http_diagnostics.jsonl"
    checkpoint = Checkpoint(args.output_dir)
    try:
        if checkpoint.exists():
            if not args.resume:
                raise ConfigError("Đã có checkpoint; dùng --resume hoặc một --output-dir mới")
            checkpoint.load(args.member_id, _id_range(args))
        else:
            if getattr(args, "existing_only", False):
                raise ConfigError("Chế độ sửa dữ liệu cần checkpoint đã có")
            if any(Path(args.output_dir).glob("*.parquet")):
                raise ConfigError("Có dữ liệu nhưng thiếu checkpoint; không tự ghi đè để chạy mới")
            checkpoint.init_new(args.member_id, _id_range(args))
    except ConfigError as error:
        logger.error("%s", error)
        raise SystemExit(2) from error
    args._drive_backup = None
    args._backup_dirty_ids, args._backup_papers, args._backup_failed = set(), 0, False
    if args.backup_dir:
        from .drive_backup import CheckpointBackup
        args._drive_backup = CheckpointBackup(args.raw_dir, args.output_dir, args.backup_dir)
    profiler = ResourceProfiler(sample_interval_sec=args.profile_interval_sec,
                                 disk_interval_sec=args.disk_profile_interval_sec,
                                 watch_dirs={"raw_sources": os.path.join(args.raw_dir, "sources"),
                                             "raw_unzipped": os.path.join(args.raw_dir, "unzipped"), "shard": args.output_dir,
                                             "network_state": str(policy.directory)},
                                 samples_path=Path(args._run_dir) / "resource_samples.jsonl")
    extra = {"run_id": args._run_id, "member_id": args.member_id, "id_range": _id_range(args),
             "is_mock": args.dry_run, "dry_run": args.dry_run, "resumed": args.resume,
             "run_args": {k: getattr(args, k) for k in ("batch_size", "rate_limit_sec", "raw_dir", "output_dir", "max_papers", "dry_run",
                                                       "s2_rate_limit_sec", "s2_max_attempts", "s2_cooldown_sec", "s2_background_retries",
                                                       "s2_recovery_passes", "s2_drain_budget_sec", "run_budget_sec",
                                                        "s2_recovery_max_wait_sec", "s2_incomplete_recheck_sec",
                                                       "s2_batch_size", "checkpoint_every_papers",
                                                       "rate_state_dir", "max_rate_wait_sec",
                                                       "auto_resume_rate_limit",
                                                       "recheck_missing",
                                                       "recheck_bib_fallback",
                                                       "source_rate_limit_sec", "backup_dir", "backup_every_papers",
                                                       "source_download_attempts", "source_read_timeout_sec", "source_max_seconds",
                                                       "source_endpoint", "max_inflight_papers", "disk_profile_interval_sec")}}
    extra["runtime_scope"] = "profiler start through final data backup; excludes final output backup and notebook validation"
    extra["disk_scope"] = "raw sources, extracted files, shard and network state; excludes external course export and Drive backup"
    extra["run_args"]["existing_only"] = getattr(args, "existing_only", False)
    extra["source_code_hash"] = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    profiler.start()
    args._run_deadline = time.monotonic()+args.run_budget_sec
    args._paused_time_budget = False
    try:
        if args._drive_backup:
            try:
                with profiler.phase("drive_backup"):
                    args._drive_backup.save()
            except BaseException:
                args._backup_failed = True
                raise
        extra["results"] = _run_with_rate_resume(args, profiler, checkpoint, policy, extra)
        if args.export_course:
            with profiler.phase("export"):
                export_to_course_spec(args.output_dir, args.course_export_dir or os.path.join(args.output_dir, "course_export"))
        active = any(policy.snapshot(provider)["remaining_sec"] > 0 for provider in ("arxiv", "semantic_scholar"))
        paused = getattr(args, "_paused_rate_limit", False) or (extra["results"]["failed"] and active)
        extra["status"] = ("dry_run" if args.dry_run else "paused_time_budget" if getattr(args, "_paused_time_budget", False)
                           else "paused_rate_limit" if paused else "completed_with_errors" if extra["results"]["failed"] else "completed")
    except (arXivRateLimitError, CooldownDeferred) as error:
        extra.update(status="paused_rate_limit", error=str(error))
    except BaseException as error:
        extra["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        extra["error"] = repr(error)
        raise
    finally:
        extra["s2_requests"] = get_request_stats()
        try:
            extra["rate_limits"] = {provider: policy.snapshot(provider) for provider in ("arxiv", "semantic_scholar")}
            extra["rate_state_dir"] = str(policy.directory)
            extra["retry_after_sec"] = max(row["remaining_sec"] for row in extra["rate_limits"].values())
        except RuntimeError as error:
            extra["rate_state_error"] = str(error)
        backup_error = None
        if args._drive_backup and not args._backup_failed:
            try:
                with profiler.phase("drive_backup"):
                    args._drive_backup.save(args._backup_dirty_ids)
                args._backup_dirty_ids.clear()
                extra["drive_backup"] = args._drive_backup.summary()
            except BaseException as error:
                backup_error = error
                args._backup_failed = True
                extra.update(status="backup_failed", backup_error=str(error))
        stats = profiler.stop_and_export(os.path.join(args._run_dir, "stats.json"), extra=extra)
        processed = stats.get("results", {}).get("processed_this_run", 0)
        if "results" in stats:
            stats["results"]["profiled_avg_sec_this_run"] = stats["runtime_sec"] / processed if processed else None
        _write_json_atomic(os.path.join(args._run_dir, "stats.json"), stats)
        _write_json_atomic(os.path.join(args.output_dir, "stats.json"), stats)
        if args._drive_backup and not args._backup_failed:
            try:
                args._drive_backup.save(args._backup_dirty_ids, include_outputs=True)
            except BaseException as error:
                stats.update(status="backup_failed", backup_error=str(error))
                _write_json_atomic(os.path.join(args._run_dir, "stats.json"), stats)
                _write_json_atomic(os.path.join(args.output_dir, "stats.json"), stats)
                raise
        if backup_error is not None:
            raise backup_error
        logger.info("Run %s: %s, %.3f giây", args._run_id, stats["status"], stats["runtime_sec"])


if __name__ == "__main__":
    main()
