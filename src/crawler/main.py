"""CLI thu thập metadata, nguồn và trích dẫn; hỗ trợ resume và đo tài nguyên.

Phụ trách: Trịnh Vỹ Triết (24120474).
"""

import argparse
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
from datetime import datetime, timezone
from pathlib import Path
from itertools import islice
from typing import Any, Iterable, Iterator

from .discovery import discover_metadata_batch
from .id_range import iter_assigned_arxiv_ids
from .profiler import ResourceProfiler
from .reference_scraper import ReferenceResult, scrape_references_for_paper, get_request_stats, configure_request_policy, reset_request_stats
from .reference_batch import scrape_references_batch, complete_batch_result
from .records import base_id, merge_publications, merge_references, sources_complete, tex_complete, REFERENCE_TERMINAL, REFERENCE_REPLACE
from .observations import save_observations, request_delta, combine_request_metrics
from .profiler import _write_json_atomic
from .source_downloader import download_and_clean_source
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
    parser.add_argument("--s2-batch-size", type=_positive_int, default=5,
                        help="Số paper/request S2, tối đa 500; đặt 1 để gọi riêng")
    parser.add_argument("--rate-state-dir", help="Thư mục lưu cooldown dùng chung qua các lượt chạy")
    parser.add_argument("--max-rate-wait-sec", type=_non_negative_float, default=180.0,
                        help="Khoảng chờ inline tối đa; lâu hơn thì lưu checkpoint và tạm dừng")
    parser.add_argument("--auto-resume-rate-limit", action="store_true",
                        help="Lưu checkpoint, chờ cooldown arXiv rồi tự tiếp tục; có thể Stop khi đang chờ")
    parser.add_argument("--recheck-missing", action="store_true",
                        help="Kiểm tra lại các ID đã đánh dấu missing trong phạm vi lượt chạy")
    parser.add_argument("--checkpoint-every-papers", type=_positive_int, default=1,
                        help="Lưu checkpoint sau số paper này, độc lập với batch API")
    parser.add_argument("--s2-max-attempts", type=_positive_int, default=3,
                        help="Số lần thử S2 trong một lượt (mặc định: 3)")
    parser.add_argument("--s2-cooldown-sec", type=_non_negative_float, default=60.0,
                        help="Thời gian nghỉ S2 sau khi hết lượt HTTP 429")
    parser.add_argument("--source-download-attempts", type=_positive_int, default=3,
                        help="Số lần tải một version trong mỗi lượt (mặc định: 3)")
    parser.add_argument("--source-rate-limit-sec", type=_non_negative_float, default=3.0,
                        help="Khoảng nghỉ tải full-text, tối thiểu 1 giây")
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
    if args.rate_limit_sec < 3 or args.source_rate_limit_sec < 1:
        parser.error("Metadata cần >= 3 giây; tải nguồn cần >= 1 giây")
    if args.s2_rate_limit_sec < 1 or min(args.source_read_timeout_sec, args.source_max_seconds, args.max_rate_wait_sec) <= 0:
        parser.error("--s2-rate-limit-sec phải >= 1; timeout/ngân sách tải nguồn phải > 0")
    if args.s2_batch_size > 500:
        parser.error("--s2-batch-size không vượt quá 500")
    if args.existing_only and not args.resume:
        parser.error("--existing-only cần --resume")
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


def _version_reusable(paper_id: str, version: dict, unzipped_dir: str) -> bool:
    if not re.fullmatch(r"v[1-9]\d*", str(version.get("version") or "")):
        return False
    return check_source_version(Path(unzipped_dir).parent, paper_id, version)["verified"]


def _process_paper(arxiv_id: str, args: argparse.Namespace, profiler: ResourceProfiler,
                   sources_dir: str, unzipped_dir: str, paper_record: dict | None = None,
                   previous_references: list | None = None, previous_observation: dict | None = None,
                   prefetched_references: ReferenceResult | None = None) -> tuple[dict, list[dict]]:
    paper = paper_record if paper_record is not None else {"id": arxiv_id}
    dry_run = getattr(args, "dry_run", False)
    versions = paper.get("versions") or []
    if not versions:
        raise ValueError(f"Thiếu thông tin version của {arxiv_id}; cần xác minh metadata")
    paper["id"] = arxiv_id
    summary = {"arxiv_id": arxiv_id, "version_results": [], "versions_attempted": 0, "versions_reused": 0}
    for version in versions:
        tag = version.get("version") or ""
        if not re.fullmatch(r"v[1-9]\d*", tag):
            raise ValueError(f"Version không hợp lệ: {tag!r}")
        if dry_run:
            version["source_status"] = "pending"
            continue
        if _version_reusable(arxiv_id, version, unzipped_dir):
            summary["versions_reused"] += 1
            continue
        summary["versions_attempted"] += 1
        try:
            with profiler.phase("download_clean"):
                result = download_and_clean_source(arxiv_id + tag, sources_dir, unzipped_dir,
                                                   rate_limit_sec=getattr(args, "source_rate_limit_sec", 3.0),
                                                   max_attempts=getattr(args, "source_download_attempts", 3),
                                                   read_timeout_sec=getattr(args, "source_read_timeout_sec", 90.0),
                                                   max_elapsed_sec=getattr(args, "source_max_seconds", 180.0))
        except NotImplementedError:
            raise
        except Exception as error:
            result = {"status": "error", "error_message": repr(error)}
        status = result.get("status")
        version["source_status"] = "success" if status == "ok" else status or "error"
        for field in ("size_before_bytes", "size_after_bytes"):
            if result.get(field) is not None:
                version[field] = result[field]
        summary["version_results"].append(result)
        profiler.capture()
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
    old = previous_observation or {}
    if dry_run:
        references = []
        observation = {"arxiv_id": arxiv_id, "reference_status": "dry_run", "reference_update": "keep"}
    elif old.get("reference_status") in REFERENCE_TERMINAL:
        references = previous_references or []
        observation = {**old, "reference_update": "keep"}
    else:
        before = get_request_stats()
        try:
            with profiler.phase("references"):
                local = os.path.join(unzipped_dir, arxiv_id.replace("/", "_"))
                interval = getattr(args, "s2_rate_limit_sec", 5.0)
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
                       "request_group": getattr(prefetched_references, "request_group", None),
                       "request_group_size": getattr(prefetched_references, "request_group_size", 1),
                       **combine_request_metrics(getattr(prefetched_references, "request_metrics", None) or {},
                                                 request_delta(before, get_request_stats()))}
        if status == "not_indexed":
            observation["expected_count"] = None
    summary["observation"] = observation
    return summary, list(references)


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


def run_pipeline(args: argparse.Namespace, profiler: ResourceProfiler, checkpoint: Checkpoint) -> dict:
    pipeline_started = time.perf_counter()
    publications, references, observations = _materialize(checkpoint)
    state = checkpoint.state
    missing = set(state.get("confirmed_missing", []))
    sources_dir, unzipped_dir = os.path.join(args.raw_dir, "sources"), os.path.join(args.raw_dir, "unzipped")
    os.makedirs(sources_dir, exist_ok=True)
    os.makedirs(unzipped_dir, exist_ok=True)
    with profiler.phase("id_generation"):
        if not hasattr(args, "_assigned_ids"):
            all_ids = sorted(publications) if getattr(args, "existing_only", False) else list(
                iter_assigned_arxiv_ids(args.start_month, args.start_id, args.end_month, args.end_id))
            args._assigned_ids = all_ids[:args.max_papers] if args.max_papers else all_ids
        all_ids = args._assigned_ids
    if getattr(args, "recheck_missing", False) and not getattr(args, "_missing_rechecked", False):
        count = len(missing.intersection(all_ids))
        missing.difference_update(all_ids)
        args._missing_rechecked = True
        if count:
            logger.info("Kiểm tra lại %d ID đã đánh dấu missing", count)
    pending = [key for key in all_ids if key not in missing and
               (key not in publications or not all(_version_reusable(key, v, unzipped_dir) for v in publications[key].get("versions", []))
                or not sources_complete(publications[key]) or observations.get(key, {}).get("reference_status") not in REFERENCE_TERMINAL)]
    pending_at_start = len(pending)
    deferred_s2 = []
    if rate_limiter.policy.snapshot("semantic_scholar")["remaining_sec"] > 0:
        for key in pending:
            paper = publications.get(key)
            if (paper and observations.get(key, {}).get("reference_status") == "api_error"
                    and sources_complete(paper)
                    and all(_version_reusable(key, version, unzipped_dir) for version in paper.get("versions", []))):
                deferred_s2.append(key)
        deferred_set = set(deferred_s2)
        pending = [key for key in pending if key not in deferred_set]
        if deferred_s2:
            logger.info("Hoãn %d bài chỉ còn lỗi S2 đến khi hết cooldown", len(deferred_s2))
    deferred = getattr(args, "_rate_deferred_ids", set())
    pending.sort(key=lambda key: key in deferred)
    logger.info("Phạm vi %d ID; %d cần xử lý, %d đã đủ hoặc đã xác nhận không tồn tại",
                len(all_ids), len(pending), len(all_ids) - len(pending))
    attempted_versions = reused_versions = 0
    errors = dict(state.get("failed", {}))
    metrics = []
    metrics_path = Path(args._run_dir) / "paper_metrics.jsonl"
    metrics_path.touch(exist_ok=True)
    visited_ids = 0
    for batch in _batched(pending, args.batch_size):
        need_discovery = [key for key in batch if key not in publications or not publications[key].get("versions")]
        found = {key: deepcopy(publications[key]) for key in batch if key in publications and key not in need_discovery}
        discovery_started = time.perf_counter()
        if need_discovery:
            with profiler.phase("discovery"):
                try:
                    metadata = discover_metadata_batch(need_discovery, rate_limit_sec=args.rate_limit_sec)
                    for record in metadata:
                        key = _record_id(record)
                        if key in batch:
                            found[key] = merge_publications(publications.get(key), record)
                    failures = getattr(metadata, "failed_ids", {})
                    for key in need_discovery:
                        if key in failures:
                            errors[key] = str(failures[key])
                        elif key not in found:
                            if key in getattr(metadata, "missing_confirmed", set()):
                                missing.add(key)
                                errors.pop(key, None)
                            else:
                                errors[key] = "discovery: ID chưa được xác minh trong feed"
                except NotImplementedError:
                    raise
                except (arXivRateLimitError, CooldownDeferred) as error:
                    args._paused_rate_limit = True
                    args._rate_retry_after = getattr(error, "retry_after", None)
                    errors.update({key: f"discovery: {error!r}" for key in need_discovery})
                except Exception as error:
                    errors.update({key: f"discovery: {error!r}" for key in need_discovery})
        discovery_sec = time.perf_counter() - discovery_started
        if not found and rate_limiter.policy.snapshot("arxiv")["remaining_sec"] > 0:
            args._paused_rate_limit = True
        prefetched = {}
        reference_batch_sec = 0.0
        needs_references = [key for key in batch if key in found and
                            observations.get(key, {}).get("reference_status") not in REFERENCE_TERMINAL]
        if needs_references and not args.dry_run and args.s2_batch_size > 1:
            began = time.perf_counter()
            with profiler.phase("references"):
                prefetched = scrape_references_batch(needs_references, rate_limit_sec=args.s2_rate_limit_sec,
                                                       batch_size=args.s2_batch_size)
            reference_batch_sec = time.perf_counter() - began
        batch_pubs, batch_refs, batch_status, batch_metrics = [], [], [], []
        visited_this_batch = 0

        def flush_checkpoint():
            nonlocal errors
            batch_no = checkpoint.state["next_batch"]
            storage_started = time.perf_counter()
            next_state = deepcopy(checkpoint.state)
            with profiler.phase("storage"):
                for kind, rows, writer in (("publications", batch_pubs, save_publications_parquet),
                                           ("references", batch_refs, save_references_parquet),
                                           ("statuses", batch_status, save_observations)):
                    if rows:
                        name = f"{kind}_{batch_no:05d}.parquet"
                        writer(rows, checkpoint.part_path(name))
                        next_state["parts"].setdefault(kind, []).append(name)
            storage_sec = time.perf_counter() - storage_started
            current = _summary(publications, references, observations, missing, errors)
            errors = dict(current["failed_ids"])
            next_state.update({"schema_version": 2, "next_batch": batch_no + 1, "confirmed_missing": sorted(missing),
                               "done_ids": sorted(set(publications) | missing), "failed": errors, "counts": current,
                               "paper_states": {key: {"sources": {v["version"]: v.get("source_status") for v in p.get("versions", [])},
                                                      "reference_status": observations.get(key, {}).get("reference_status", "unknown")}
                                                for key, p in publications.items()}})
            _write_json_atomic(checkpoint.path, next_state)
            checkpoint.state = next_state
            backup = getattr(args, "_drive_backup", None)
            if backup:
                args._backup_papers += len(batch_pubs)
                if args._backup_papers >= args.backup_every_papers:
                    try:
                        with profiler.phase("drive_backup"):
                            backup.save(args._backup_dirty_ids)
                    except BaseException:
                        args._backup_failed = True
                        raise
                    args._backup_dirty_ids.clear()
                    args._backup_papers = 0
            with metrics_path.open("a", encoding="utf-8") as stream:
                for metric in batch_metrics:
                    metric["storage_allocated_sec"] = storage_sec / max(1, len(batch_metrics))
                    metric["elapsed_sec"] = (metric["compute_sec"] + metric["discovery_allocated_sec"]
                                             + metric["reference_batch_allocated_sec"] + metric["storage_allocated_sec"])
                    stream.write(json.dumps(metric) + "\n")
                    metrics.append(metric)
            logger.info("Đã lưu checkpoint %d: %d paper, %d hoàn tất, %d cần retry",
                        batch_no, len(batch_pubs), current["succeeded"], current["failed"])
            for rows in (batch_pubs, batch_refs, batch_status, batch_metrics):
                rows.clear()

        for key in batch:
            visited_this_batch += 1
            if key not in found:
                continue
            if not found[key].get("versions"):
                errors[key] = "discovery: thiếu thông tin version; cần xác minh lại"
                continue
            if getattr(args, "_drive_backup", None):
                args._backup_dirty_ids.add(key)
            started = time.perf_counter()
            download, new_refs = _process_paper(key, args, profiler, sources_dir, unzipped_dir,
                                                found[key], references.get(key), observations.get(key), prefetched.get(key))
            pub = merge_publications(publications.get(key), found[key])
            obs = download["observation"]
            publications[key] = pub
            if obs["reference_update"] == "replace":
                references[key] = merge_references(new_refs)
            elif obs["reference_update"] == "merge":
                references[key] = merge_references([*references.get(key, []), *new_refs])
            observations[key] = obs
            attempted_versions += download["versions_attempted"]
            reused_versions += download["versions_reused"]
            batch_pubs.append(pub)
            if obs["reference_update"] != "keep":
                batch_refs.extend(new_refs)
            batch_status.append(obs)
            batch_metrics.append({"arxiv_id": key, "compute_sec": time.perf_counter() - started,
                                  "discovery_allocated_sec": discovery_sec / max(1, len(found)),
                                  "reference_batch_allocated_sec": reference_batch_sec / max(1, len(prefetched)) if key in prefetched else 0.0,
                                  "versions_attempted": download["versions_attempted"],
                                  "versions_reused": download["versions_reused"], "run_id": args._run_id})
            if len(batch_pubs) >= args.checkpoint_every_papers:
                flush_checkpoint()
            if download.get("rate_limited"):
                args._paused_rate_limit = True
                args._rate_retry_after = download.get("retry_after_sec")
                args._rate_failed_id = key
                break
        if batch_pubs or not found or any(key in errors for key in batch):
            flush_checkpoint()
        current = _summary(publications, references, observations, missing, errors)
        visited_ids += visited_this_batch
        remaining_ids = len(pending) - visited_ids
        eta_hours = ((time.perf_counter() - pipeline_started) / visited_ids * remaining_ids / 3600)
        logger.info("Tiến độ: %d/%d ID trong lượt; %d hoàn tất, %d cần retry; ước tính lượt còn lại %.2f giờ",
                    visited_ids, len(pending), current["succeeded"], current["failed"], eta_hours)
        if getattr(args, "_paused_rate_limit", False):
            break
    with profiler.phase("storage"):
        save_publications_parquet([publications[key] for key in sorted(publications)], os.path.join(args.output_dir, "publications.parquet"))
        save_references_parquet([row for key in sorted(references) for row in references[key]], os.path.join(args.output_dir, "references.parquet"))
        save_observations([observations[key] for key in sorted(observations)], os.path.join(args.output_dir, "crawl_status.parquet"))
    current = _summary(publications, references, observations, missing, errors)
    current.update(total_ids=len(all_ids), processed_this_run=len(metrics), pending_at_start=pending_at_start,
                   deferred_s2_cooldown=len(deferred_s2),
                   versions_attempted=attempted_versions, versions_reused=reused_versions,
                   avg_paper_sec_this_run=sum(m["elapsed_sec"] for m in metrics) / len(metrics) if metrics else None)
    current["pending_after_run"] = sum(key not in missing and (key not in publications or not sources_complete(publications[key])
                                      or observations.get(key, {}).get("reference_status") not in REFERENCE_TERMINAL) for key in all_ids)
    return current


def _wait_for_arxiv(args, profiler, policy, extra):
    backup = getattr(args, "_drive_backup", None)
    if backup:
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
                state = policy.snapshot("arxiv")
                remaining = state["remaining_sec"] if state.get("not_before") else max(0, fallback_deadline - time.monotonic())
                if remaining <= 0:
                    return
                logger.info("Full đang chờ arXiv %.0fs; checkpoint đã lưu, hết cooldown sẽ tự tiếp tục. Stop để dừng.", remaining)
                time.sleep(min(15.0, remaining))
    finally:
        extra["auto_rate_limit_wait_sec"] += max(0, time.monotonic() - started)


def _run_with_rate_resume(args, profiler, checkpoint, policy, extra):
    extra.update(auto_rate_limit_resumes=0, auto_rate_limit_wait_sec=0.0, pipeline_passes=0)
    first_pending = None
    args._rate_deferred_ids = set()
    while True:
        args._paused_rate_limit = False
        args._rate_retry_after = None
        args._rate_failed_id = None
        extra["pipeline_passes"] += 1
        try:
            current = run_pipeline(args, profiler, checkpoint)
        except (arXivRateLimitError, CooldownDeferred) as error:
            if not args.auto_resume_rate_limit:
                raise
            args._paused_rate_limit = True
            args._rate_retry_after = getattr(error, "retry_after", None)
            extra["last_rate_limit_error"] = str(error)
            current = None
        except BaseException:
            pubs, refs, observations = _materialize(checkpoint)
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
        if not args.auto_resume_rate_limit or not args._paused_rate_limit:
            return current
        if args._rate_failed_id:
            args._rate_deferred_ids.add(args._rate_failed_id)
            logger.info("Hoãn %s về cuối hàng đợi; tiếp tục các ID khác sau cooldown", args._rate_failed_id)
        _wait_for_arxiv(args, profiler, policy, extra)
        extra["auto_rate_limit_resumes"] += 1
        logger.info("Tiếp tục toàn dải sau cooldown arXiv, lần %d; giữ các ID đã xong",
                    extra["auto_rate_limit_resumes"])


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
                                 watch_dirs={"raw_sources": os.path.join(args.raw_dir, "sources"),
                                             "raw_unzipped": os.path.join(args.raw_dir, "unzipped"), "shard": args.output_dir,
                                             "network_state": str(policy.directory)})
    extra = {"run_id": args._run_id, "member_id": args.member_id, "id_range": _id_range(args),
             "is_mock": args.dry_run, "dry_run": args.dry_run, "resumed": args.resume,
             "run_args": {k: getattr(args, k) for k in ("batch_size", "rate_limit_sec", "raw_dir", "output_dir", "max_papers", "dry_run",
                                                       "s2_rate_limit_sec", "s2_max_attempts", "s2_cooldown_sec",
                                                       "s2_batch_size", "checkpoint_every_papers",
                                                       "rate_state_dir", "max_rate_wait_sec",
                                                       "auto_resume_rate_limit",
                                                       "recheck_missing",
                                                       "source_rate_limit_sec", "backup_dir", "backup_every_papers",
                                                       "source_download_attempts", "source_read_timeout_sec", "source_max_seconds")}}
    extra["runtime_scope"] = "profiler start through final data backup; excludes final output backup and notebook validation"
    extra["disk_scope"] = "raw sources, extracted files, shard and network state; excludes external course export and Drive backup"
    extra["run_args"]["existing_only"] = getattr(args, "existing_only", False)
    extra["source_code_hash"] = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    profiler.start()
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
        extra["status"] = "dry_run" if args.dry_run else "paused_rate_limit" if paused else "completed_with_errors" if extra["results"]["failed"] else "completed"
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
