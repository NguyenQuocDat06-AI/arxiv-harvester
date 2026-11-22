"""CLI và pipeline đầu cuối cho Milestone 3 — Reference Matching (tối ưu RAM cho Colab 12 GiB)."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import json
import math
from pathlib import Path
import random
import time
from typing import Any

import psutil
import pyarrow.parquet as pq

from .features import build_candidate_features, fit_title_tfidf, load_m2_citation_context
from .labeling import (
    BibEntry,
    RefCandidate,
    assign_member_id,
    build_labeled_dataset,
    prepare_bib_entry,
    prepare_ref_candidate,
    write_manual_labels_jsonl,
)
from .model import build_predictions_arrow_table, run_matching_models


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 ** 2)


def _parquet_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        files = sorted(path.glob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"No parquet files found under {path}")
        return files
    raise FileNotFoundError(f"Input path does not exist: {path}")


def _count_arxiv_ids_in_parquet(path: Path, col: str = "arxiv_id") -> Counter[str]:
    counts: Counter[str] = Counter()
    for f in _parquet_files(path):
        pf = pq.ParquetFile(f)
        if pf.metadata.num_rows == 0:
            continue
        for batch in pf.iter_batches(batch_size=65536, columns=[col]):
            counts.update(str(v) for v in batch.column(col).to_pylist() if v)
    return counts


def _load_refs_for_papers(references_path: Path, allowed_papers: set[str]) -> dict[str, list[RefCandidate]]:
    refs_by_paper: dict[str, list[RefCandidate]] = defaultdict(list)
    for f in _parquet_files(references_path):
        pf = pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=65536):
            for row in batch.to_pylist():
                pid = row.get("arxiv_id")
                if pid in allowed_papers and row.get("ref_arxiv_id"):
                    refs_by_paper[str(pid)].append(prepare_ref_candidate(row))
    return refs_by_paper


def _load_bibtex_for_papers(bibtex_dir: Path, allowed_papers: set[str]) -> dict[str, list[BibEntry]]:
    files = _parquet_files(bibtex_dir)
    target_stems = {pid.replace("/", "_").replace(".", "-") for pid in allowed_papers}
    matched = [f for f in files if f.stem in target_stems]
    scan_files = matched if (matched and len(matched) >= max(1, int(0.5 * len(target_stems)))) else files

    bib_by_paper: dict[str, list[BibEntry]] = defaultdict(list)
    for f in scan_files:
        pf = pq.ParquetFile(f)
        if pf.metadata.num_rows == 0:
            continue
        for batch in pf.iter_batches(batch_size=32768):
            for row in batch.to_pylist():
                pid = row.get("arxiv_id")
                if pid in allowed_papers:
                    bib_by_paper[str(pid)].append(prepare_bib_entry(row))
    return bib_by_paper


def _preselect_working_papers(
    paper_ids: list[str],
    bib_counts: Counter[str],
    ref_counts: Counter[str],
    *,
    auto_fraction: float,
    seed: int,
    max_train_auto: int | None,
    per_member_manual: int = 5,
    min_manual_q: int = 20,
) -> set[str]:
    """Lọc trước tập ứng viên gọn (~3.200 bài) để chỉ nạp BibEntry/RefCandidate cần thiết vào RAM."""
    rng = random.Random(seed)
    pubs_by_member: dict[str, list[str]] = defaultdict(list)
    for pid in sorted(set(paper_ids)):
        pubs_by_member[assign_member_id(pid)].append(pid)

    k_members = len(pubs_by_member)
    selected: set[str] = set()

    # 1. Chọn sẵn ứng viên rộng rãi cho tập manual mỗi thành viên (tối đa 40 bài/thành viên để chấm lọc)
    for mid, pids in sorted(pubs_by_member.items()):
        manual_cands = [p for p in pids if bib_counts.get(p, 0) >= min_manual_q and ref_counts.get(p, 0) >= min_manual_q]
        if len(manual_cands) < per_member_manual:
            manual_cands = [p for p in pids if bib_counts.get(p, 0) >= min_manual_q and ref_counts.get(p, 0) >= 5]
        rng.shuffle(manual_cands)
        selected.update(manual_cands[: max(per_member_manual * 8, 40)])

    # 2. Chọn sẵn tập tự động đủ lớn (>= auto_fraction của phần còn lại + đệm 5%)
    remaining = max(0, len(paper_ids) - per_member_manual * k_members)
    target_auto = max(2 * k_members, math.ceil(max(0.10, auto_fraction) * remaining))
    if max_train_auto is not None:
        target_auto = min(max_train_auto + 2 * k_members, max(2 * k_members, remaining))
    buffer_target = int(target_auto * 1.05) + 50

    eligible_by_member: dict[str, list[str]] = {}
    for mid, pids in sorted(pubs_by_member.items()):
        cands = [p for p in pids if p not in selected and bib_counts.get(p, 0) >= 1 and ref_counts.get(p, 0) >= 1]
        rng.shuffle(cands)
        eligible_by_member[mid] = cands

    added = 0
    ptrs = {mid: 0 for mid in sorted(eligible_by_member)}
    while added < buffer_target:
        progressed = False
        for mid in sorted(eligible_by_member):
            pool = eligible_by_member[mid]
            idx = ptrs[mid]
            if idx < len(pool):
                selected.add(pool[idx])
                ptrs[mid] = idx + 1
                added += 1
                progressed = True
                if added >= buffer_target:
                    break
        if not progressed:
            break

    return selected


def run_pipeline(
    *,
    papers_path: str | Path,
    references_path: str | Path,
    parsed_dir: str | Path,
    output_dir: str | Path,
    manual_labels_path: str | Path | None = None,
    auto_fraction: float = 0.12,
    seed: int = 42,
    max_train_auto: int | None = None,
) -> dict[str, Any]:
    """Chạy toàn bộ pipeline Milestone 3 từ M1/M2 Parquet tới bảng predictions & báo cáo đánh giá."""
    t0 = time.perf_counter()
    parsed_root = Path(parsed_dir)
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    # 1. Đọc danh sách arxiv_id & đếm số dòng BibTeX / Reference bằng streaming nhẹ RAM
    paper_ids: list[str] = []
    for f in _parquet_files(Path(papers_path)):
        for batch in pq.ParquetFile(f).iter_batches(batch_size=65536, columns=["arxiv_id"]):
            paper_ids.extend(str(v) for v in batch.column("arxiv_id").to_pylist() if v)
    paper_ids = sorted(set(paper_ids))

    ref_counts = _count_arxiv_ids_in_parquet(Path(references_path), "arxiv_id")
    bib_counts = _count_arxiv_ids_in_parquet(parsed_root / "bibtex", "arxiv_id")
    print(
        f"[m3_pipeline] Indexed corpus: papers={len(paper_ids):,}, "
        f"with_refs={len(ref_counts):,}, with_bibtex={len(bib_counts):,} (rss={_rss_mb():.0f} MiB)",
        flush=True,
    )

    # 2. Chỉ nạp BibEntry & RefCandidate cho tập ứng viên cần thiết (~3.200 bài thay vì toàn bộ 25.000 bài)
    working_papers = _preselect_working_papers(
        paper_ids,
        bib_counts,
        ref_counts,
        auto_fraction=auto_fraction,
        seed=seed,
        max_train_auto=max_train_auto,
    )
    if manual_labels_path is not None and Path(manual_labels_path).is_file():
        for line in Path(manual_labels_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                working_papers.add(str(json.loads(line)["arxiv_id"]))

    refs_by_paper = _load_refs_for_papers(Path(references_path), working_papers)
    bib_by_paper = _load_bibtex_for_papers(parsed_root / "bibtex", working_papers)
    print(
        f"[m3_pipeline] Loaded working subset: {len(working_papers):,} papers, "
        f"{sum(len(v) for v in bib_by_paper.values()):,} BibTeX entries, "
        f"{sum(len(v) for v in refs_by_paper.values()):,} refs (rss={_rss_mb():.0f} MiB)",
        flush=True,
    )

    # 3. Gán nhãn Manual + Automatic và chia train/valid/test theo từng thành viên
    labeled_entries, label_summary = build_labeled_dataset(
        paper_ids,
        bib_by_paper,
        refs_by_paper,
        auto_fraction=auto_fraction,
        seed=seed,
        manual_labels_path=manual_labels_path,
        max_train_auto=max_train_auto,
    )
    print(
        f"[m3_pipeline] Labeled: manual={label_summary['manual_papers']} papers ({label_summary['manual_entries']:,} entries), "
        f"auto={label_summary['auto_papers']:,} papers ({label_summary['auto_entries']:,} entries) (rss={_rss_mb():.0f} MiB)",
        flush=True,
    )

    manual_truth_map = {
        (e.arxiv_id, e.citation_key): (e.groundtruth_arxiv_id, e.match_reason, e.confidence)
        for e in labeled_entries
        if e.label_source == "manual"
    }
    write_manual_labels_jsonl(
        out_root / "manual_labels.jsonl",
        label_summary["manual_paper_ids"],
        bib_by_paper,
        refs_by_paper,
        manual_truth_map,
    )

    # Cắt bỏ các bài không trúng chọn khỏi RAM trước khi tải M2 hierarchy
    target_papers = set(label_summary["paper_partition"].keys())
    bib_by_paper = {pid: v for pid, v in bib_by_paper.items() if pid in target_papers}
    refs_by_paper = {pid: v for pid, v in refs_by_paper.items() if pid in target_papers}
    gc.collect()

    # 4. Đọc ngữ cảnh cây phân cấp M2 (chỉ cho ~3.022 bài đã chọn)
    hierarchy_context = load_m2_citation_context(parsed_root, target_papers)
    print(
        f"[m3_pipeline] Loaded M2 hierarchy context: {len(hierarchy_context):,} citation keys (rss={_rss_mb():.0f} MiB)",
        flush=True,
    )

    # 5. Huấn luyện TF-IDF trên tập train và trích 25 đặc trưng cho từng cặp ứng viên
    tfidf = fit_title_tfidf(labeled_entries, bib_by_paper, refs_by_paper)
    feature_bundle = build_candidate_features(
        labeled_entries,
        bib_by_paper,
        refs_by_paper,
        tfidf=tfidf,
        hierarchy_context=hierarchy_context,
    )
    n_pairs = int(len(feature_bundle["y"]))
    n_pos_pairs = int(feature_bundle["y"].sum())
    n_hctx = len(hierarchy_context)

    # Giải phóng dữ liệu văn bản trung gian trước khi huấn luyện mô hình
    del bib_by_paper, refs_by_paper, hierarchy_context, tfidf, labeled_entries
    gc.collect()
    print(
        f"[m3_pipeline] Built feature matrix: {n_pairs:,} pairs x 25 features "
        f"(positives={n_pos_pairs:,}, rss={_rss_mb():.0f} MiB)",
        flush=True,
    )

    # 6. Huấn luyện mô hình, chạy Ablation Study và chọn mô hình tốt nhất theo Validation MRR@5
    model_output = run_matching_models(feature_bundle, seed=seed)
    df_preds = model_output["predictions_df"]

    # 7. Xuất bảng predictions dạng Parquet chuẩn
    pred_table = build_predictions_arrow_table(df_preds)
    pred_dir = out_root / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)
    pred_file = pred_dir / "predictions-00000.parquet"
    pq.write_table(pred_table, pred_file, compression="snappy")

    elapsed_sec = round(time.perf_counter() - t0, 3)

    results_summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": elapsed_sec,
        "seed": seed,
        "labeling": {k: v for k, v in label_summary.items() if k not in {"paper_partition", "manual_paper_ids"}},
        "manual_paper_ids": label_summary["manual_paper_ids"],
        "candidate_pairs_total": n_pairs,
        "candidate_positive_pairs": n_pos_pairs,
        "hierarchy_context_keys": n_hctx,
        "predictions_rows": int(pred_table.num_rows),
        "best_model": model_output["best_model"],
        "models": model_output["models"],
    }

    (out_root / "m3_results_summary.json").write_text(
        json.dumps(results_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_root / "m3_feature_importance.json").write_text(
        json.dumps(model_output["feature_importance"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_root / "m3_ablation.json").write_text(
        json.dumps(model_output["ablation"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_root / "m3_error_analysis.json").write_text(
        json.dumps(model_output["error_analysis"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return results_summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="arxiv-matcher",
        description="Run Milestone 3 Reference Matching pipeline and produce predictions Parquet.",
    )
    parser.add_argument("--papers", required=True, help="Path to M1 course_export/papers.parquet or dir")
    parser.add_argument("--references", required=True, help="Path to M1 course_export/references.parquet or dir")
    parser.add_argument("--parsed-dir", required=True, help="Path to M2 parsed directory (elements, hierarchy, bibtex)")
    parser.add_argument("--output-dir", required=True, help="Output directory for predictions and M3 reports")
    parser.add_argument("--manual-labels", default=None, help="Optional pre-edited manual_labels.jsonl")
    parser.add_argument("--auto-fraction", type=float, default=0.12, help="Fraction of remaining papers to auto-label (>= 0.10)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic split")
    parser.add_argument("--max-train-auto", type=int, default=None, help="Optional cap on auto papers for smoke tests")
    args = parser.parse_args(argv)

    summary = run_pipeline(
        papers_path=args.papers,
        references_path=args.references,
        parsed_dir=args.parsed_dir,
        output_dir=args.output_dir,
        manual_labels_path=args.manual_labels,
        auto_fraction=args.auto_fraction,
        seed=args.seed,
        max_train_auto=args.max_train_auto,
    )
    best = summary["best_model"]
    test_m = summary["models"][best]["test"]
    print(
        f"[arxiv-matcher] DONE best_model={best} test_MRR@5={test_m['mrr_at_5']:.4f} "
        f"test_R@1={test_m['recall_at_1']:.4f} predictions_rows={summary['predictions_rows']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
