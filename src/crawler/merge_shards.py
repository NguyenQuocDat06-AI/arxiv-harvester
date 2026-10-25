"""Khung gộp phân vùng. Phụ trách: Dương Phan Minh Trí (24120470)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import string
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import pyarrow.parquet as pq

from .storage import (
    PUBLICATIONS_SCHEMA,
    REFERENCES_SCHEMA,
    save_publications_parquet,
    save_references_parquet,
)

logger = logging.getLogger(__name__)

_VERSION_SUFFIX_RE = re.compile(r"v\d+$")
_PUNCTUATION_RE = re.compile(f"[{re.escape(string.punctuation)}]")


def _normalize_title_for_dedup(title: str | None) -> str:
    """Chuẩn hóa tiêu đề: lowercase, loại bỏ dấu câu và khoảng trắng thừa."""
    if not title:
        return ""
    cleaned = _PUNCTUATION_RE.sub(" ", title.lower())
    return " ".join(cleaned.split())


def _clean_base_id(raw_id: str | None) -> str | None:
    if not raw_id:
        return None
    s = str(raw_id).strip()
    return _VERSION_SUFFIX_RE.sub("", s) if s else None


def _count_null_fields(record: dict) -> int:
    """Đếm số trường có giá trị None trong bản ghi."""
    return sum(1 for val in record.values() if val is None)


def _check_id_coverage(
    assigned_range: Any,
    paper_ids: set[str],
    member_id: str | None = None,
) -> dict[str, Any]:
    """Kiểm tra độ phủ ID: so sánh tập ID thu thập được với dải ID được giao.
    - Cùng tháng: kiểm tra 100% các ID từ start_id đến end_id.
    - Vắt tháng:
      + Đoạn tháng cuối: kiểm tra đủ từ 00001 đến end_id.
      + Đoạn tháng đầu: kiểm tra lỗ hổng (gaps) từ start_id đến max_id tìm thấy của tháng đó;
        đánh dấu tail_unverified=True vì không biết bài cuối tháng nếu không query trực tiếp.
    """
    if not assigned_range:
        return {
            "has_assigned_range": False,
            "total_found": len(paper_ids),
            "missing_count": 0,
            "out_of_range_count": 0,
            "tail_unverified": False,
        }

    try:
        if not isinstance(assigned_range, dict):
            raise TypeError(f"assigned_range phải là dict, nhận {type(assigned_range).__name__}")

        start_m = assigned_range.get("start_month")
        end_m = assigned_range.get("end_month")
        if start_m is None or end_m is None:
            raise KeyError("Thiếu start_month hoặc end_month trong id_range")

        start_id = int(assigned_range["start_id"])
        end_id = int(assigned_range["end_id"])

        # Đưa YYYY-MM hoặc YYMM về dạng YYMM
        def to_yymm(m: str) -> str:
            clean = str(m).replace("-", "").strip()
            return clean[2:] if len(clean) == 6 else clean[-4:]

        start_yymm = to_yymm(str(start_m))
        end_yymm = to_yymm(str(end_m))
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        logger.warning(
            "Member/Shard %s: id_range có định dạng không hợp lệ %r: %s",
            member_id or "unknown",
            assigned_range,
            exc,
        )
        return {
            "has_assigned_range": False,
            "total_found": len(paper_ids),
            "missing_count": 0,
            "out_of_range_count": 0,
            "tail_unverified": False,
            "coverage_error": str(exc),
        }

    missing_ids = set()
    out_of_range_ids = set()
    tail_unverified = False

    if start_yymm == end_yymm:
        expected_ids = {f"{start_yymm}.{seq:05d}" for seq in range(start_id, end_id + 1)}
        missing_ids = expected_ids - paper_ids
        out_of_range_ids = paper_ids - expected_ids
    else:
        # Dải vắt qua 2 tháng (ví dụ 2406 -> 2407)
        tail_unverified = True
        # 1. Tháng cuối: kỳ vọng từ 00001 đến end_id
        end_month_expected = {f"{end_yymm}.{seq:05d}" for seq in range(1, end_id + 1)}
        end_month_found = {p for p in paper_ids if p.startswith(f"{end_yymm}.")}
        missing_ids.update(end_month_expected - end_month_found)
        out_of_range_ids.update(end_month_found - end_month_expected)

        # 2. Tháng đầu: kỳ vọng từ start_id đến max_seq_found của tháng đầu
        start_month_found = {p for p in paper_ids if p.startswith(f"{start_yymm}.")}
        if start_month_found:
            seqs = [int(p.split(".")[1]) for p in start_month_found]
            max_seq = max(seqs)
            min_seq = min(seqs)
            # Nếu có bài nhỏ hơn start_id -> out of range
            if min_seq < start_id:
                out_of_range_ids.update({p for p in start_month_found if int(p.split(".")[1]) < start_id})
            # Kiểm tra lỗ hổng từ start_id đến max_seq
            expected_start_window = {f"{start_yymm}.{seq:05d}" for seq in range(start_id, max_seq + 1)}
            missing_ids.update(expected_start_window - start_month_found)
        else:
            # Không tìm thấy bài nào của tháng đầu
            missing_ids.add(f"{start_yymm}.{start_id:05d}+")

        # Các bài không thuộc cả 2 tháng
        other_months_found = {p for p in paper_ids if not (p.startswith(f"{start_yymm}.") or p.startswith(f"{end_yymm}."))}
        out_of_range_ids.update(other_months_found)

    return {
        "has_assigned_range": True,
        "assigned_range": assigned_range,
        "total_found": len(paper_ids),
        "missing_count": len(missing_ids),
        "missing_ids_sample": sorted(list(missing_ids))[:10],
        "out_of_range_count": len(out_of_range_ids),
        "out_of_range_ids_sample": sorted(list(out_of_range_ids))[:10],
        "tail_unverified": tail_unverified,
    }


def merge_all_shards(
    shards_dir: str | None = None,
    output_dir: str | None = None,
    allow_mock: bool = False,
    skip_corrupted: bool = False,
) -> dict[str, Any]:
    """Gộp Parquet và thống kê của các thành viên thành dữ liệu chung.
    
    Quy tắc:
    - allow_mock=False (mặc định): từ chối gộp nếu có shard mock. Dữ liệu thật đọc từ data/shards và xuất ra data/processed.
    - allow_mock=True: cho phép dữ liệu mock, mặc định đọc từ data/mock/shards và xuất ra data/mock/processed để tách biệt hoàn toàn với dữ liệu thật.
    - Cấm tuyệt đối trộn lẫn shard mock và shard thật (ném ValueError).
    - Khử trùng publications theo base ID: ưu tiên updated mới hơn -> ít null hơn -> deterministic.
    - Khử trùng references phân cấp: ref_s2_id -> ref_arxiv_id -> ref_doi -> ref_title chuẩn hóa.
    - Đếm reference mồ côi.
    - Tính overall_stats: total_compute_sec, max_member_wall_sec, weighted avg RSS, source_version_coverage_rate.
    """
    is_default_shards = (shards_dir is None)
    if shards_dir is None:
        shards_dir = "data/mock/shards" if allow_mock else "data/shards"
    if output_dir is None:
        if is_default_shards:
            output_dir = "data/mock/processed" if allow_mock else "data/processed"
        else:
            # shards_dir không phải mặc định -> xuất ra processed cạnh shards_dir (không ghi vào data/processed của repo)
            parent_dir = os.path.dirname(os.path.abspath(shards_dir))
            output_dir = os.path.join(parent_dir, "processed")

    if not os.path.exists(shards_dir):
        raise FileNotFoundError(f"Thư mục shards không tồn tại: {shards_dir}")

    os.makedirs(output_dir, exist_ok=True)

    shard_dirs = sorted([
        os.path.join(shards_dir, d)
        for d in os.listdir(shards_dir)
        if os.path.isdir(os.path.join(shards_dir, d)) and not d.startswith((".", "_"))
    ])

    if not shard_dirs:
        raise ValueError(f"Không tìm thấy thư mục phân vùng nào trong '{shards_dir}'")

    raw_pubs: list[dict] = []
    raw_refs: list[dict] = []
    all_stats: list[dict] = []
    member_breakdown: list[dict] = []
    corrupted_shards: list[str] = []

    mock_flags: set[bool] = set()

    for sdir in shard_dirs:
        mid = os.path.basename(sdir)
        pub_path = os.path.join(sdir, "publications.parquet")
        ref_path = os.path.join(sdir, "references.parquet")
        stats_path = os.path.join(sdir, "stats.json")

        # Kiểm tra tính toàn vẹn shard
        if not (os.path.exists(pub_path) and os.path.exists(ref_path) and os.path.exists(stats_path)):
            corrupted_shards.append(mid)
            if skip_corrupted:
                logger.warning("Bỏ qua shard lỗi/thiếu file: %s", mid)
                continue
            raise FileNotFoundError(f"Shard '{mid}' thiếu một trong các tệp bắt buộc (publications, references, stats.json)")

        try:
            pub_table = pq.read_table(pub_path)
            ref_table = pq.read_table(ref_path)
            with open(stats_path, encoding="utf-8") as f:
                stats = json.load(f)
        except Exception as exc:
            corrupted_shards.append(mid)
            if skip_corrupted:
                logger.warning("Bỏ qua shard hỏng: %s (%s)", mid, exc)
                continue
            raise ValueError(f"Lỗi khi đọc dữ liệu shard '{mid}': {exc}") from exc

        # Kiểm tra schema khớp chuẩn
        if pub_table.schema != PUBLICATIONS_SCHEMA:
            corrupted_shards.append(mid)
            if skip_corrupted:
                logger.warning("Shard %s sai schema publications", mid)
                continue
            raise ValueError(f"Shard '{mid}' có schema publications không khớp chuẩn!")

        if ref_table.schema != REFERENCES_SCHEMA:
            corrupted_shards.append(mid)
            if skip_corrupted:
                logger.warning("Shard %s sai schema references", mid)
                continue
            raise ValueError(f"Shard '{mid}' có schema references không khớp chuẩn!")

        is_mock_shard = bool(stats.get("is_mock", True))
        mock_flags.add(is_mock_shard)

        s_pubs = pub_table.to_pylist()
        s_refs = ref_table.to_pylist()

        # Tính độ phủ ID của shard
        shard_ids = {p["id"] for p in s_pubs if p.get("id")}
        coverage = _check_id_coverage(stats.get("id_range"), shard_ids, member_id=mid)

        # So sánh số lượng bài tìm thấy với stats.results.total_ids nếu có
        res_total = stats.get("results", {}).get("total_ids")
        if res_total is not None and res_total != len(shard_ids):
            coverage["mismatch_with_results_total"] = {
                "results_total_ids": res_total,
                "actual_publications_found": len(shard_ids),
                "difference": len(shard_ids) - res_total,
            }
            logger.warning(
                "Shard %s: lệch số bài giữa stats.results.total_ids (%d) và publications.parquet (%d)",
                mid, res_total, len(shard_ids)
            )

        mem_info = stats.get("memory", {})
        results_info = stats.get("results", {})
        member_breakdown.append({
            "member_id": mid,
            "is_mock": is_mock_shard,
            "publications_count": len(s_pubs),
            "references_count": len(s_refs),
            "runtime_sec": stats.get("runtime_sec", 0.0),
            "peak_rss_mb": mem_info.get("peak_rss_mb", 0.0),
            "avg_rss_mb": mem_info.get("avg_rss_mb", 0.0),
            "os_reported_peak_rss_mb": mem_info.get("os_reported_peak_rss_mb"),
            "num_samples": mem_info.get("num_samples", 0),
            "phases": stats.get("phases", {}),
            "results": results_info,
            "papers_with_synthesized_v1": stats.get("papers_with_synthesized_v1"),
            "disk_bytes": sum(d.get("after_bytes", 0) for d in stats.get("disk", {}).get("dirs", {}).values()),
            "id_coverage": coverage,
            "environment": stats.get("environment", {}),
        })

        raw_pubs.extend(s_pubs)
        raw_refs.extend(s_refs)
        all_stats.append(stats)

    # Kiểm tra cấm trộn lẫn Mock và Real
    if True in mock_flags and False in mock_flags:
        raise ValueError("CẢNH BÁO VI PHẠM: Tồn tại đồng thời cả shard Mock và shard Thật! Cấm tuyệt đối trộn lẫn dữ liệu mock vào dữ liệu thật.")

    is_overall_mock = (True in mock_flags)
    if is_overall_mock and not allow_mock:
        raise ValueError("Dữ liệu trong shards là dữ liệu MOCK (is_mock=True). merge_shards mặc định từ chối gộp mock. Dùng --allow-mock nếu muốn chạy kiểm thử.")

    # 1. Khử trùng publications theo base ID
    unique_pubs: dict[str, dict] = {}
    dup_pub_count = 0

    for p in raw_pubs:
        base_id = _clean_base_id(p.get("id"))
        if not base_id:
            continue
        p["id"] = base_id  # Đảm bảo lưu base ID

        if base_id not in unique_pubs:
            unique_pubs[base_id] = p
        else:
            dup_pub_count += 1
            # Quy tắc chọn bản ghi tốt nhất:
            existing = unique_pubs[base_id]
            ext_up = existing.get("updated")
            cur_up = p.get("updated")

            # Ưu tiên updated mới hơn
            if cur_up and (not ext_up or cur_up > ext_up):
                unique_pubs[base_id] = p
            elif cur_up == ext_up:
                # Ưu tiên ít null hơn
                if _count_null_fields(p) < _count_null_fields(existing):
                    unique_pubs[base_id] = p

    sorted_pubs = [unique_pubs[k] for k in sorted(unique_pubs)]

    # 2. Khử trùng references phân cấp
    unique_refs: dict[tuple, dict] = {}
    dup_ref_count = 0

    for r in raw_refs:
        src_id = _clean_base_id(r.get("arxiv_id"))
        if not src_id:
            continue
        r["arxiv_id"] = src_id

        # Khóa phân cấp: ref_s2_id -> ref_arxiv_id -> ref_doi -> ref_title chuẩn hóa
        ref_s2 = r.get("ref_s2_id")
        ref_arxiv = _clean_base_id(r.get("ref_arxiv_id"))
        ref_doi = r.get("ref_doi")
        norm_title = _normalize_title_for_dedup(r.get("ref_title"))

        if ref_s2:
            dedup_key = (src_id, "s2", ref_s2)
        elif ref_arxiv:
            dedup_key = (src_id, "arxiv", ref_arxiv)
        elif ref_doi:
            dedup_key = (src_id, "doi", ref_doi.lower().strip())
        elif norm_title:
            dedup_key = (src_id, "title", norm_title)
        elif r.get("raw_citation") is not None:
            dedup_key = (src_id, "raw", str(r.get("raw_citation")))
        else:
            dedup_key = (src_id, "record", json.dumps(r, sort_keys=True, default=str))

        if dedup_key not in unique_refs:
            unique_refs[dedup_key] = r
        else:
            dup_ref_count += 1

    # Sắp xếp references theo arxiv_id tăng dần, null xếp cuối
    sorted_refs = sorted(
        unique_refs.values(),
        key=lambda x: (x["arxiv_id"], x.get("ref_arxiv_id") or "zzzzzzzzz"),
    )

    # 3. Đếm reference mồ côi
    valid_pub_ids = set(unique_pubs.keys())
    orphan_count = sum(1 for r in sorted_refs if r["arxiv_id"] not in valid_pub_ids)

    # 4. Lưu publications.parquet và references.parquet
    out_pub_path = os.path.join(output_dir, "publications.parquet")
    out_ref_path = os.path.join(output_dir, "references.parquet")
    save_publications_parquet(sorted_pubs, out_pub_path)
    save_references_parquet(sorted_refs, out_ref_path)

    # 5. Tính toán overall_stats.json
    total_compute_sec = round(sum(m["runtime_sec"] for m in member_breakdown), 3)
    max_member_wall_sec = round(max((m["runtime_sec"] for m in member_breakdown), default=0.0), 3)
    avg_sec_per_paper = round(total_compute_sec / len(sorted_pubs), 3) if sorted_pubs else None

    # Cộng dồn phases giữa các shard
    aggregated_phases: dict[str, dict[str, Any]] = {}
    for m in member_breakdown:
        for phase_name, p_data in m.get("phases", {}).items():
            if phase_name not in aggregated_phases:
                aggregated_phases[phase_name] = {"elapsed_sec": 0.0, "calls": 0}
            aggregated_phases[phase_name]["elapsed_sec"] = round(
                aggregated_phases[phase_name]["elapsed_sec"] + p_data.get("elapsed_sec", 0.0), 3
            )
            aggregated_phases[phase_name]["calls"] += p_data.get("calls", 0)

    # Nguồn dự phòng: cộng dồn results từ stats.json
    stats_results_backup = {
        "total_ids": sum(m.get("results", {}).get("total_ids", 0) for m in member_breakdown),
        "succeeded": sum(m.get("results", {}).get("succeeded", 0) for m in member_breakdown),
        "failed": sum(m.get("results", {}).get("failed", 0) for m in member_breakdown),
        "not_found": sum(m.get("results", {}).get("not_found", 0) for m in member_breakdown),
        "source_size_before_bytes": sum(m.get("results", {}).get("source_size_before_bytes", 0) for m in member_breakdown),
        "source_size_after_bytes": sum(m.get("results", {}).get("source_size_after_bytes", 0) for m in member_breakdown),
    }
    stats_total_ids = stats_results_backup["total_ids"]
    paper_success_rate_from_stats = (
        round(stats_results_backup["succeeded"] / stats_total_ids, 4) if stats_total_ids > 0 else None
    )

    peak_rss = max((m["peak_rss_mb"] for m in member_breakdown), default=0.0)
    os_reported_peak_rss = max(
        (m["os_reported_peak_rss_mb"] for m in member_breakdown if m["os_reported_peak_rss_mb"] is not None),
        default=None
    )
    total_samples = sum(m["num_samples"] for m in member_breakdown)
    if total_samples > 0:
        weighted_avg_rss = round(
            sum(m["avg_rss_mb"] * m["num_samples"] for m in member_breakdown) / total_samples, 2
        )
    else:
        weighted_avg_rss = 0.0

    shard_end_disk = max((m["disk_bytes"] for m in member_breakdown), default=0)

    # Tính dung lượng data/processed/
    final_output_disk = 0
    for root, _, files in os.walk(output_dir):
        for f in files:
            final_output_disk += os.path.getsize(os.path.join(root, f))

    # Thống kê trạng thái nguồn & tỷ lệ bao phủ version nguồn
    status_counts = Counter(p.get("source_status") for p in sorted_pubs)
    has_any_source_status = any(p.get("source_status") is not None for p in sorted_pubs)
    has_any_source_size = any(p.get("size_before_bytes") is not None for p in sorted_pubs)

    if has_any_source_status:
        success_or_partial = status_counts["success"] + status_counts["partial_success"]
        paper_success_rate = round(success_or_partial / len(sorted_pubs), 4) if sorted_pubs else None
    else:
        paper_success_rate = None

    # Tỷ lệ version có dữ liệu nguồn
    total_versions_found = sum(len(p.get("versions") or []) for p in sorted_pubs)
    versions_with_source_data = sum(
        sum(1 for v in (p.get("versions") or []) if v.get("source_status") is not None)
        for p in sorted_pubs
    )
    if has_any_source_status and total_versions_found > 0:
        source_ver_cov_rate = round(versions_with_source_data / total_versions_found, 4)
    else:
        source_ver_cov_rate = None

    avg_versions_per_paper = (
        round(total_versions_found / len(sorted_pubs), 2) if sorted_pubs else None
    )

    total_source_size_before = sum(p.get("size_before_bytes") or 0 for p in sorted_pubs) if has_any_source_size else None
    total_source_size_after = sum(p.get("size_after_bytes") or 0 for p in sorted_pubs) if has_any_source_size else None

    # papers_with_synthesized_v1 chỉ lấy từ stats.json của từng shard (ở cấp gốc hoặc trong results)
    reported_synthesized_v1: list[int] = []
    for s in all_stats:
        val = None
        if "papers_with_synthesized_v1" in s:
            val = s["papers_with_synthesized_v1"]
        elif "results" in s and isinstance(s["results"], dict) and "papers_with_synthesized_v1" in s["results"]:
            val = s["results"]["papers_with_synthesized_v1"]
        if val is not None:
            try:
                reported_synthesized_v1.append(int(val))
            except (ValueError, TypeError):
                pass

    overall_stats = {
        "is_mock": is_overall_mock,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_publications_before_dedup": len(raw_pubs),
        "total_publications": len(sorted_pubs),
        "total_references_before_dedup": len(raw_refs),
        "total_references": len(sorted_refs),
        "orphan_references_count": orphan_count,
        "duplicate_publications_removed": dup_pub_count,
        "duplicate_references_removed": dup_ref_count,
        "source_status_breakdown": dict(status_counts) if has_any_source_status else {},
        "paper_crawl_success_rate": paper_success_rate,
        "paper_success_rate_from_stats": paper_success_rate_from_stats,
        "source_version_coverage_rate": source_ver_cov_rate,
        "avg_versions_per_paper": avg_versions_per_paper,
        "total_source_size_before_bytes": total_source_size_before,
        "total_source_size_after_bytes": total_source_size_after,
        "stats_results_backup": stats_results_backup,
        "phases_aggregated": aggregated_phases,
        "resource_performance": {
            "total_compute_sec": total_compute_sec,
            "max_member_wall_sec": max_member_wall_sec,
            "avg_sec_per_paper": avg_sec_per_paper,
            "peak_rss_mb": peak_rss,
            "os_reported_peak_rss_mb": os_reported_peak_rss,
            "weighted_avg_rss_mb": weighted_avg_rss,
            "shard_end_disk_bytes": shard_end_disk,
            "final_output_disk_bytes": final_output_disk,
            "note": "Các số đo tài nguyên được tổng hợp từ máy của 5 thành viên để theo dõi tiến độ, không thay thế cho bài benchmark chính thức trên Google Colab CPU-only.",
        },
        "corrupted_or_skipped_shards": corrupted_shards,
        "member_breakdown": member_breakdown,
    }

    # Nếu không shard nào báo key này thì không ghi vào overall_stats; nếu có thì cộng lại và thêm note
    if reported_synthesized_v1:
        overall_stats["papers_with_synthesized_v1"] = sum(reported_synthesized_v1)
        overall_stats["synthesized_v1_note"] = "Chỉ tính từ các shard có báo cáo số này trong stats.json."

    stats_out = os.path.join(output_dir, "overall_stats.json")
    tmp_stats_out = f"{stats_out}.tmp.{os.getpid()}"
    try:
        with open(tmp_stats_out, "w", encoding="utf-8") as f:
            json.dump(overall_stats, f, ensure_ascii=False, indent=2)
        os.replace(tmp_stats_out, stats_out)
    finally:
        if os.path.exists(tmp_stats_out):
            try:
                os.remove(tmp_stats_out)
            except OSError:
                pass

    print("\n================ TỔNG KẾT GỘP DỮ LIỆU (MERGE SUMMARY) ================")
    print(f"[*] Chế độ: {'MOCK DATA' if is_overall_mock else 'DỮ LIỆU THẬT'}")
    print(f"[*] Tổng bài báo trước khử trùng: {len(raw_pubs):,}")
    print(f"[*] Tổng bài báo sau khử trùng: {len(sorted_pubs):,} (đã lọc {dup_pub_count} trùng lặp)")
    print(f"[*] Tổng trích dẫn trước khử trùng: {len(raw_refs):,}")
    print(f"[*] Tổng trích dẫn sau khử trùng: {len(sorted_refs):,} (đã lọc {dup_ref_count} trùng lặp)")
    print(f"[*] Trích dẫn mồ côi: {orphan_count}")
    if "papers_with_synthesized_v1" in overall_stats:
        print(f"[*] Số bài báo tự động tổng hợp v1 mặc định (từ stats.json): {overall_stats['papers_with_synthesized_v1']}")
    print(f"[*] Tỷ lệ bài báo crawl thành công (từ Parquet): {f'{paper_success_rate * 100:.1f}%' if paper_success_rate is not None else 'n/a'}")
    print(f"[*] Tỷ lệ bài báo crawl thành công (từ stats.json): {f'{paper_success_rate_from_stats * 100:.1f}%' if paper_success_rate_from_stats is not None else 'n/a'}")
    print(f"[*] Tỷ lệ version có dữ liệu nguồn: {f'{source_ver_cov_rate * 100:.1f}%' if source_ver_cov_rate is not None else 'n/a'}")
    print(f"[*] Peak RAM: {peak_rss} MB (OS reported: {os_reported_peak_rss} MB) | Weighted Avg RAM: {weighted_avg_rss} MB")
    print(f"[*] Total Compute: {total_compute_sec}s | Max Member Wall: {max_member_wall_sec}s | Avg sec/paper: {avg_sec_per_paper}s")
    print(f"[*] File xuất: {out_pub_path}, {out_ref_path}, {stats_out}")
    print("=======================================================================\n")

    return overall_stats


def main(argv: list[str] | None = None) -> None:
    """CLI cho merge_shards."""
    parser = argparse.ArgumentParser(
        prog="python -m src.crawler.merge_shards",
        description="Gộp các phân vùng dữ liệu cá nhân thành bộ dữ liệu tổng hợp chuẩn hóa.",
    )
    parser.add_argument(
        "--shards-dir",
        default=None,
        help="Thư mục chứa các phân vùng cá nhân (mặc định: data/shards, hoặc data/mock/shards nếu có --allow-mock)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Thư mục xuất dữ liệu tổng hợp (mặc định: data/processed, hoặc data/mock/processed nếu có --allow-mock)",
    )
    parser.add_argument(
        "--allow-mock",
        action="store_true",
        default=False,
        help="Cho phép gộp shard chứa dữ liệu mock (mặc định: False)",
    )
    parser.add_argument(
        "--skip-corrupted",
        action="store_true",
        default=False,
        help="Bỏ qua các shard bị hỏng hoặc thiếu file thay vì dừng chương trình",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    merge_all_shards(
        shards_dir=args.shards_dir,
        output_dir=args.output_dir,
        allow_mock=args.allow_mock,
        skip_corrupted=args.skip_corrupted,
    )


if __name__ == "__main__":
    main()
