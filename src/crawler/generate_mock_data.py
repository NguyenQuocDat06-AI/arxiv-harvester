"""Khung sinh dữ liệu mẫu. Phụ trách: Dương Phan Minh Trí (24120470)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone

from .storage import (
    save_publications_parquet,
    save_references_parquet,
    get_synthesized_v1_count,
)

logger = logging.getLogger(__name__)

# Phân công nhiệm vụ 5 thành viên (MSSV và dải ID theo README)
MEMBERS_CONFIG = [
    {
        "member_id": "24120282",  # Nguyễn Quốc Đạt
        "name": "Nguyễn Quốc Đạt",
        "id_range": {
            "start_month": "2024-12",
            "start_id": 18848,
            "end_month": "2025-01",
            "end_id": 2641,
        },
        "sample_ids": [
            "2412.18848",
            "2412.18849",
            "2412.18850",
            "2501.00001",
            "2501.00002",
        ],
    },
    {
        "member_id": "24120237",  # Nguyễn Đình Tuấn
        "name": "Nguyễn Đình Tuấn",
        "id_range": {
            "start_month": "2025-02",
            "start_id": 3235,
            "end_month": "2025-02",
            "end_id": 8234,
        },
        "sample_ids": [
            "2502.03235",
            "2502.03236",
            "2502.03237",
            "2502.03238",
            "2502.03239",
        ],
    },
    {
        "member_id": "24120438",  # Trần Nguyên Tân
        "name": "Trần Nguyên Tân",
        "id_range": {
            "start_month": "2024-07",
            "start_id": 12839,
            "end_month": "2024-07",
            "end_id": 17838,
        },
        "sample_ids": [
            "2407.12839",
            "2407.12840",
            "2407.12841",
            "2407.12842",
            "2407.12843",
        ],
    },
    {
        "member_id": "24120470",  # Dương Phan Minh Trí
        "name": "Dương Phan Minh Trí",
        "id_range": {
            "start_month": "2024-06",
            "start_id": 17938,
            "end_month": "2024-07",
            "end_id": 2838,
        },
        "sample_ids": [
            "2406.17937",  # Cố tình trùng 1 bài với Triết để kiểm thử khử trùng lặp
            "2406.17938",
            "2406.17939",
            "2407.00001",
            "2407.00002",
        ],
    },
    {
        "member_id": "24120474",  # Trịnh Vỹ Triết
        "name": "Trịnh Vỹ Triết",
        "id_range": {
            "start_month": "2024-06",
            "start_id": 12938,
            "end_month": "2024-06",
            "end_id": 17937,
        },
        "sample_ids": [
            "2406.12938",
            "2406.12939",
            "2406.12940",
            "2406.17936",
            "2406.17937",  # Trùng với Trí
        ],
    },
]


def _check_real_data_guard(shard_dir: str, force: bool) -> bool:
    """Kiểm tra an toàn: nếu thư mục không rỗng và không có cờ mock thì từ chối ghi đè."""
    if not os.path.exists(shard_dir):
        return True
    entries = os.listdir(shard_dir)
    if not entries or entries == [".gitkeep"]:
        return True

    stats_path = os.path.join(shard_dir, "stats.json")
    if os.path.exists(stats_path):
        try:
            with open(stats_path, encoding="utf-8") as f:
                stats = json.load(f)
            if stats.get("is_mock") is True:
                return True
        except Exception:
            pass

    # Nếu có file mà không xác nhận được is_mock=True
    if not force:
        logger.warning(
            "Bỏ qua thư mục %s vì đang chứa dữ liệu (có thể là dữ liệu thật). Dùng --force để ghi đè.",
            shard_dir,
        )
        return False
    return True


def generate_single_shard_mock_data(
    cfg: dict,
    output_dir: str,
    force: bool = False,
    rng: random.Random | None = None,
) -> bool:
    """Sinh dữ liệu mock cho 1 shard cá nhân."""
    member_id = cfg["member_id"]
    shard_dir = os.path.join(output_dir, member_id)

    if not _check_real_data_guard(shard_dir, force):
        return False

    os.makedirs(shard_dir, exist_ok=True)
    if rng is None:
        rng = random.Random(42)

    sample_ids = cfg["sample_ids"]
    pubs = []
    refs = []

    for idx, paper_id in enumerate(sample_ids):
        # Tạo dữ liệu kết hợp 2 chiều:
        # idx 0, 1: bài báo có metrics từng version
        # idx >= 2: bài báo chỉ có metrics cấp bài
        is_detailed_version = (idx < 2)

        has_multi_ver = (idx % 2 == 1)
        if has_multi_ver:
            versions = [
                {
                    "version": "v1",
                    "created": "2024-06-01T10:00:00Z",
                    "size_before_bytes": 12000 if is_detailed_version else None,
                    "size_after_bytes": 4500 if is_detailed_version else None,
                    "source_status": "success" if is_detailed_version else None,
                },
                {
                    "version": "v2",
                    "created": "2024-06-05T12:00:00Z",
                    "size_before_bytes": 15000 if is_detailed_version else None,
                    "size_after_bytes": 5000 if is_detailed_version else None,
                    "source_status": "success" if is_detailed_version else None,
                },
            ]
        else:
            versions = [
                {
                    "version": "v1",
                    "created": "2024-06-01T08:00:00Z",
                    "size_before_bytes": 8000 if is_detailed_version else None,
                    "size_after_bytes": 3000 if is_detailed_version else None,
                    "source_status": "success" if is_detailed_version else None,
                }
            ]

        # Trạng thái tải cấp bài
        if idx == 3:
            st = "no_latex"
            sb, sa = 2000, 2000
        elif idx == 4:
            st = "error"
            sb, sa = 0, 0
        else:
            st = "success"
            sb = 27000 if has_multi_ver else 8000
            sa = 9500 if has_multi_ver else 3000

        # Ca biên kiểm thử theo yêu cầu:
        # 1. Ca thiếu title / authors / abstract (bài idx == 2 của phân vùng 24120470)
        is_missing_metadata = (member_id == "24120470" and idx == 2)
        title_val = None if is_missing_metadata else f"Mock Paper Title for {paper_id}"
        abstract_val = None if is_missing_metadata else f"Abstract of simulated paper {paper_id} for data analysis test."
        authors_val = [] if is_missing_metadata else [f"Author {chr(65 + idx)}", f"CoAuthor {chr(66 + idx)}"]

        # 2. Ca versions rỗng (bài idx == 3 của phân vùng 24120470)
        is_empty_versions = (member_id == "24120470" and idx == 3)
        if is_empty_versions:
            versions = []

        pub = {
            "id": paper_id,
            "title": title_val,
            "abstract": abstract_val,
            "authors": authors_val,
            "primary_category": "cs.AI",
            "categories": ["cs.AI", "cs.LG"],
            "published": "2024-06-01T08:00:00Z",
            "updated": "2024-06-05T12:00:00Z",
            "doi": f"10.1234/mock.{paper_id}",
            "journal_ref": "Mock Conference 2024" if idx % 2 == 0 else None,
            "comments": "8 pages" if idx % 2 == 0 else None,
            "venue": "Mock Conference 2024" if idx % 2 == 0 else None,
            "source_status": st,
            "size_before_bytes": sb,
            "size_after_bytes": sa,
            "versions": versions,
        }
        pubs.append(pub)

        # Sinh references:
        # idx == 0: không có reference nào (test ca rỗng)
        # idx == 1: có reference arXiv và DOI
        # idx >= 2: có reference fallback từ .bib
        if idx == 1:
            refs.append({
                "arxiv_id": paper_id,
                "ref_arxiv_id": "2301.00010",
                "ref_title": "Foundational deep learning paper",
                "ref_authors": ["Goodfellow, Ian"],
                "ref_submission_date": "2023-01-15",
                "ref_s2_id": "s2_mock_111",
                "ref_doi": "10.1000/mock.doi",
                "ref_year": 2023,
                "ref_venue": "NeurIPS",
                "raw_citation": None,
                "source": "semantic_scholar",
            })
        elif idx >= 2:
            refs.append({
                "arxiv_id": paper_id,
                "ref_arxiv_id": None,  # Không có trên arXiv
                "ref_title": f"Classic textbook citation for {paper_id}",
                "ref_authors": ["Knuth, Donald"],
                "ref_submission_date": None,
                "ref_s2_id": None,
                "ref_doi": None,
                "ref_year": 1997,
                "ref_venue": "Addison-Wesley",
                "raw_citation": "@book{knuth1997art, title={The Art of Computer Programming}}",
                "source": "bib_fallback",
            })

    # Lưu Parquet
    pub_path = os.path.join(shard_dir, "publications.parquet")
    ref_path = os.path.join(shard_dir, "references.parquet")
    c_before = get_synthesized_v1_count()
    save_publications_parquet(pubs, pub_path)
    shard_synthesized = get_synthesized_v1_count() - c_before
    save_references_parquet(refs, ref_path)

    # Sinh stats.json đúng chuẩn ResourceProfiler của Triết
    stats_data = {
        "member_id": member_id,
        "id_range": cfg["id_range"],
        "is_mock": True,
        "status": "completed",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_sec": round(rng.uniform(15.0, 35.0), 3),
        "phases": {
            "id_generation": {"elapsed_sec": 0.05, "calls": 1},
            "discovery": {"elapsed_sec": 2.5, "calls": 1},
            "download_clean": {"elapsed_sec": 12.0, "calls": len(sample_ids)},
            "references": {"elapsed_sec": 5.0, "calls": len(sample_ids)},
            "storage": {"elapsed_sec": 0.4, "calls": 2},
        },
        "memory": {
            "metric": "RSS của tiến trình Python (không phải RAM toàn máy)",
            "unit": "MB",
            "bytes_per_mb": 1024**2,
            "peak_rss_mb": round(rng.uniform(120.0, 180.0), 2),
            "avg_rss_mb": round(rng.uniform(80.0, 110.0), 2),
            "num_samples": 40,
            "sample_interval_sec": 0.5,
        },
        "disk": {
            "unit": "bytes",
            "dirs": {
                "shard": {
                    "path": shard_dir,
                    "before_bytes": 0,
                    "after_bytes": 1024 * 50,
                }
            },
        },
        "environment": {
            "platform": "Linux-Mock-Platform",
            "python_version": sys.version.split()[0],
            "cpu_only": True,
            "cpu_count_logical": 4,
            "total_memory_mb": 8192.0,
        },
        "results": {
            "total_ids": len(sample_ids),
            "succeeded": 3,
            "failed": 1,
            "not_found": 0,
            "publications": len(pubs),
            "references": len(refs),
            "source_size_before_bytes": sum(p["size_before_bytes"] or 0 for p in pubs),
            "source_size_after_bytes": sum(p["size_after_bytes"] or 0 for p in pubs),
            "papers_with_synthesized_v1": shard_synthesized,
        },
        "papers_with_synthesized_v1": shard_synthesized,
    }

    stats_path = os.path.join(shard_dir, "stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats_data, f, ensure_ascii=False, indent=2)

    logger.info("Đã sinh thành công dữ liệu mock cho thành viên %s tại %s", member_id, shard_dir)
    return True


def generate_all_mock_data(
    shards_dir: str = "data/mock/shards",
    force: bool = False,
    seed: int = 42,
) -> None:
    """Sinh toàn bộ mock data cho cả 5 thành viên."""
    rng = random.Random(seed)
    success_count = 0
    for cfg in MEMBERS_CONFIG:
        if generate_single_shard_mock_data(cfg, shards_dir, force=force, rng=rng):
            success_count += 1
    print(f"[+] Hoàn tất sinh dữ liệu mẫu: {success_count}/{len(MEMBERS_CONFIG)} shards sẵn sàng tại '{shards_dir}'.")


def main(argv: list[str] | None = None) -> None:
    """Giao diện dòng lệnh CLI cho generate_mock_data."""
    parser = argparse.ArgumentParser(
        prog="python -m src.crawler.generate_mock_data",
        description="Sinh dữ liệu giả lập (mock data) chuẩn schema cho 5 phân vùng thành viên.",
    )
    parser.add_argument(
        "--shards-dir",
        default="data/mock/shards",
        help="Thư mục chứa các phân vùng shards (mặc định: data/mock/shards)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bắt buộc ghi đè kể cả khi thư mục đang chứa dữ liệu",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Số seed ngẫu nhiên cố định (mặc định: 42)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    generate_all_mock_data(shards_dir=args.shards_dir, force=args.force, seed=args.seed)


if __name__ == "__main__":
    main()
