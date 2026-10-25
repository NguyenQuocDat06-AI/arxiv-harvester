"""Khung CLI điều phối. Phụ trách: Trịnh Vỹ Triết (24120474)."""

import argparse
import json
import logging
import os
import re
import sys
from itertools import islice
from typing import Iterable, Iterator

from .discovery import discover_metadata_batch
from .id_range import iter_assigned_arxiv_ids
from .profiler import ResourceProfiler
from .reference_scraper import scrape_references_for_paper
from .source_downloader import download_and_clean_source
from .storage import save_publications_parquet, save_references_parquet

logger = logging.getLogger("crawler")

CHECKPOINT_DIRNAME = "_checkpoint"
STATE_FILENAME = "state.json"
_MONTH_RE = re.compile(r"^(?:(\d{4})-(\d{2})|(\d{2})(\d{2}))$")
_VERSION_RE = re.compile(r"v\d+$")


class ConfigError(Exception):
    """Lỗi cấu hình/môi trường: phải dừng toàn bộ thay vì bỏ qua từng bài."""


def _month_key(value: str) -> tuple[int, int]:
    """Đưa YYYY-MM hoặc YYMM về (năm, tháng) để so sánh thứ tự."""
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
    if number < 0:
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
        help="Khoảng nghỉ giữa các request arXiv, giây (mặc định: 3.0)",
    )
    parser.add_argument(
        "--profile-interval-sec",
        type=_non_negative_float,
        default=0.5,
        help="Chu kỳ lấy mẫu RSS, giây (mặc định: 0.5)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Tiếp tục từ checkpoint, bỏ qua các bài đã hoàn thành",
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
    """Trạng thái lưu sau từng lô: ID đã xong, lỗi và các tệp Parquet tạm."""

    def __init__(self, output_dir: str) -> None:
        self.dir = os.path.join(output_dir, CHECKPOINT_DIRNAME)
        self.path = os.path.join(self.dir, STATE_FILENAME)
        self.state: dict = {}

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def init_new(self, member_id: str, id_range: dict) -> None:
        self.state = {
            "member_id": member_id,
            "id_range": id_range,
            "next_batch": 1,
            "parts": {"publications": [], "references": []},
            "done_ids": [],
            "failed": {},
            "counts": {
                "succeeded": 0,
                "not_found": 0,
                "references": 0,
                "source_size_before_bytes": 0,
                "source_size_after_bytes": 0,
            },
        }
        os.makedirs(self.dir, exist_ok=True)
        self.save()

    def load(self, member_id: str, id_range: dict) -> None:
        with open(self.path, encoding="utf-8") as f:
            self.state = json.load(f)
        if self.state.get("member_id") != member_id or self.state.get("id_range") != id_range:
            raise ConfigError(
                "Checkpoint thuộc MSSV/khoảng ID khác; kiểm tra lại tham số hoặc --output-dir"
            )
        listed = set(self.state["parts"]["publications"] + self.state["parts"]["references"])
        for name in os.listdir(self.dir):
            # Tệp Parquet ghi dở khi tiến trình dừng giữa lô: bỏ đi để chạy lại lô đó.
            if name.endswith(".parquet") and name not in listed:
                os.remove(os.path.join(self.dir, name))

    def save(self) -> None:
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

    def part_path(self, name: str) -> str:
        return os.path.join(self.dir, name)


def _read_parts(checkpoint: Checkpoint, kind: str) -> list[dict]:
    import pyarrow.parquet as pq

    records: list[dict] = []
    for name in checkpoint.state["parts"][kind]:
        records.extend(pq.read_table(checkpoint.part_path(name)).to_pylist())
    return records


def _process_paper(
    arxiv_id: str, args: argparse.Namespace, profiler: ResourceProfiler, sources_dir: str, unzipped_dir: str
) -> tuple[dict, list[dict]]:
    """Tải/dọn nguồn và lấy trích dẫn cho một bài; lỗi được ném lên để ghi nhận."""
    with profiler.phase("download_clean"):
        download = download_and_clean_source(
            arxiv_id,
            sources_dir,
            unzipped_dir,
            rate_limit_sec=args.rate_limit_sec,
        )
    paper_dir = os.path.join(unzipped_dir, arxiv_id)
    with profiler.phase("references"):
        references = scrape_references_for_paper(
            arxiv_id,
            paper_dir if os.path.isdir(paper_dir) else None,
        )
    return download, references


def run_pipeline(args: argparse.Namespace, profiler: ResourceProfiler, checkpoint: Checkpoint) -> dict:
    """Chạy toàn bộ khoảng ID theo lô và trả số liệu tổng hợp."""
    state = checkpoint.state
    counts = state["counts"]
    done = set(state["done_ids"])
    sources_dir = os.path.join(args.raw_dir, "sources")
    unzipped_dir = os.path.join(args.raw_dir, "unzipped")
    os.makedirs(sources_dir, exist_ok=True)
    os.makedirs(unzipped_dir, exist_ok=True)

    with profiler.phase("id_generation"):
        all_ids = list(
            iter_assigned_arxiv_ids(args.start_month, args.start_id, args.end_month, args.end_id)
        )
    pending = [arxiv_id for arxiv_id in all_ids if arxiv_id not in done]
    logger.info("Tổng %d ID, đã xong %d, cần xử lý %d", len(all_ids), len(all_ids) - len(pending), len(pending))

    for batch in _batched(pending, args.batch_size):
        batch_no = state["next_batch"]
        with profiler.phase("discovery"):
            try:
                metadata = discover_metadata_batch(batch, rate_limit_sec=args.rate_limit_sec)
            except NotImplementedError:
                raise
            except Exception as exc:
                # Lỗi mạng/API của cả lô: ghi nhận để --resume chạy lại, không dừng toàn bộ.
                logger.warning("Lô %d lỗi discovery: %s", batch_no, exc)
                for arxiv_id in batch:
                    state["failed"][arxiv_id] = f"discovery: {exc!r}"
                checkpoint.save()
                continue

        found = {}
        for record in metadata:
            record_id = _record_id(record)
            if record_id in batch:
                found[record_id] = record

        publications: list[dict] = []
        references: list[dict] = []
        finished: list[str] = []
        for arxiv_id in batch:
            if arxiv_id not in found:
                counts["not_found"] += 1
                finished.append(arxiv_id)
                continue
            try:
                download, paper_refs = _process_paper(arxiv_id, args, profiler, sources_dir, unzipped_dir)
            except NotImplementedError:
                raise
            except Exception as exc:
                logger.warning("Bỏ qua %s: %s", arxiv_id, exc)
                state["failed"][arxiv_id] = repr(exc)
                continue
            publications.append(found[arxiv_id])
            references.extend(paper_refs)
            counts["succeeded"] += 1
            counts["references"] += len(paper_refs)
            counts["source_size_before_bytes"] += int(download.get("size_before_bytes") or 0)
            counts["source_size_after_bytes"] += int(download.get("size_after_bytes") or 0)
            state["failed"].pop(arxiv_id, None)
            finished.append(arxiv_id)

        # Lỗi ghi Parquet là lỗi schema/đĩa: để ném lên và dừng toàn bộ.
        with profiler.phase("storage"):
            if publications:
                name = f"publications_{batch_no:05d}.parquet"
                save_publications_parquet(publications, checkpoint.part_path(name))
                state["parts"]["publications"].append(name)
            if references:
                name = f"references_{batch_no:05d}.parquet"
                save_references_parquet(references, checkpoint.part_path(name))
                state["parts"]["references"].append(name)
        state["done_ids"].extend(finished)
        state["next_batch"] = batch_no + 1
        checkpoint.save()
        logger.info(
            "Lô %d: %d/%d bài xong, tổng thành công %d, lỗi %d",
            batch_no, len(finished), len(batch), counts["succeeded"], len(state["failed"]),
        )

    with profiler.phase("storage"):
        publications = {}
        for record in _read_parts(checkpoint, "publications"):
            publications[_record_id(record)] = record
        save_publications_parquet(
            [publications[key] for key in sorted(publications)],
            os.path.join(args.output_dir, "publications.parquet"),
        )
        save_references_parquet(
            _read_parts(checkpoint, "references"),
            os.path.join(args.output_dir, "references.parquet"),
        )

    return {
        "total_ids": len(all_ids),
        "processed_this_run": len(pending),
        "succeeded": counts["succeeded"],
        "failed": len(state["failed"]),
        "not_found": counts["not_found"],
        "publications": len(publications),
        "references": counts["references"],
        "source_size_before_bytes": counts["source_size_before_bytes"],
        "source_size_after_bytes": counts["source_size_after_bytes"],
        "failed_ids": dict(sorted(state["failed"].items())),
    }


def main(argv: list[str] | None = None) -> None:
    """Điều phối các module và lưu kết quả vào phân vùng cá nhân."""
    # Windows dùng cp1252 khi chuyển hướng output, không in được tiếng Việt.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    os.makedirs(args.output_dir, exist_ok=True)

    checkpoint = Checkpoint(args.output_dir)
    id_range = _id_range(args)
    try:
        if checkpoint.exists():
            if not args.resume:
                raise ConfigError(
                    f"Đã có checkpoint trong {checkpoint.dir}; dùng --resume để chạy tiếp "
                    "hoặc xóa thư mục này để chạy lại từ đầu"
                )
            checkpoint.load(args.member_id, id_range)
        else:
            checkpoint.init_new(args.member_id, id_range)
    except ConfigError as exc:
        logger.error("%s", exc)
        sys.exit(2)

    profiler = ResourceProfiler(
        sample_interval_sec=args.profile_interval_sec,
        watch_dirs={
            "raw_sources": os.path.join(args.raw_dir, "sources"),
            "raw_unzipped": os.path.join(args.raw_dir, "unzipped"),
            "shard": args.output_dir,
        },
    )
    stats_path = os.path.join(args.output_dir, "stats.json")
    extra = {
        "member_id": args.member_id,
        "id_range": id_range,
        "is_mock": False,
        "resumed": args.resume,
        "run_args": {
            "batch_size": args.batch_size,
            "rate_limit_sec": args.rate_limit_sec,
            "raw_dir": args.raw_dir,
            "output_dir": args.output_dir,
        },
    }
    profiler.start()
    try:
        extra["results"] = run_pipeline(args, profiler, checkpoint)
        extra["status"] = "completed"
    except BaseException as exc:
        extra["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        extra["error"] = repr(exc)
        raise
    finally:
        stats = profiler.stop_and_export(stats_path, extra=extra)
        logger.info(
            "Trạng thái %s sau %.1f s, peak RSS %.1f MB; đã ghi %s",
            stats["status"], stats["runtime_sec"], stats["memory"]["peak_rss_mb"], stats_path,
        )


if __name__ == "__main__":
    main()
