"""Phân tích định lượng đặc trưng (EDA), kiểm định chéo 5-fold và thử nghiệm áp lực (Stress-Test) cho Milestone 3."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import random
import time
from typing import Any

import lightgbm as lgb
import numpy as np
import pyarrow.parquet as pq
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from .cleaning import normalize_title, tokenize_title
from .features import (
    BASE_METADATA_FEATURES,
    FEATURE_NAMES,
    HIERARCHY_CONTEXT_FEATURES,
    PARTITION_TO_CODE,
    POOL_RELATIVE_FEATURES,
    build_candidate_features,
    fit_title_tfidf,
    load_m2_citation_context,
)
from .labeling import (
    BibEntry,
    LabeledEntry,
    RefCandidate,
    assign_member_id,
    prepare_bib_entry,
    prepare_ref_candidate,
)
from .model import _group_sizes_from_sorted_queries, compute_ranking_metrics, rank_top5_from_scores


def _collect_table_files(data_roots: list[Path], table_name: str) -> list[Path]:
    files: list[Path] = []
    for root in data_roots:
        for candidate in (root / "data" / table_name, root / table_name):
            if candidate.is_dir():
                files.extend(sorted(candidate.glob("*.parquet")))
            elif (root / f"{table_name}.parquet").is_file():
                files.append(root / f"{table_name}.parquet")
    # Loại trùng đường dẫn nếu nhiều candidate trỏ cùng file
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        rf = f.resolve()
        if rf not in seen:
            seen.add(rf)
            unique.append(rf)
    return unique


def load_labeled_corpus_from_hf_dirs(
    data_roots: list[Path],
    manual_labels_path: Path,
    *,
    max_train_papers: int | None = None,
    seed: int = 42,
) -> tuple[list[LabeledEntry], dict[str, list[BibEntry]], dict[str, list[RefCandidate]], dict[tuple[str, str], dict[str, Any]]]:
    """Nạp dữ liệu đã gán nhãn (6 bảng chuẩn HF) cho tập phân tích định lượng."""
    manual_papers: set[str] = set()
    if manual_labels_path.is_file():
        for line in manual_labels_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                manual_papers.add(str(json.loads(line)["arxiv_id"]))

    pred_files = _collect_table_files(data_roots, "predictions")
    if not pred_files:
        raise FileNotFoundError(f"Không tìm thấy bảng predictions trong {data_roots}")

    raw_preds: list[tuple[str, str, str, str | None]] = []
    train_auto_papers: set[str] = set()
    eval_and_manual_papers: set[str] = set()

    for pf_path in pred_files:
        pf = pq.ParquetFile(pf_path)
        for batch in pf.iter_batches(batch_size=65536, columns=["arxiv_id", "partition", "citation_key", "groundtruth_arxiv_id"]):
            for aid, part, ckey, gt in zip(
                batch.column("arxiv_id").to_pylist(),
                batch.column("partition").to_pylist(),
                batch.column("citation_key").to_pylist(),
                batch.column("groundtruth_arxiv_id").to_pylist(),
            ):
                aid_s = str(aid)
                part_s = str(part)
                raw_preds.append((aid_s, part_s, str(ckey), str(gt) if gt else None))
                if part_s in {"valid", "test"} or aid_s in manual_papers:
                    eval_and_manual_papers.add(aid_s)
                else:
                    train_auto_papers.add(aid_s)

    if max_train_papers is not None and len(train_auto_papers) > max_train_papers:
        rng = random.Random(seed)
        sampled_train = set(rng.sample(sorted(train_auto_papers), max_train_papers))
        selected_papers = eval_and_manual_papers | sampled_train
    else:
        selected_papers = eval_and_manual_papers | train_auto_papers

    labeled_entries: list[LabeledEntry] = []
    for aid_s, part_s, ckey_s, gt_s in raw_preds:
        if aid_s not in selected_papers:
            continue
        labeled_entries.append(
            LabeledEntry(
                arxiv_id=aid_s,
                member_id=assign_member_id(aid_s),
                citation_key=ckey_s,
                groundtruth_arxiv_id=gt_s,
                label_source="manual" if aid_s in manual_papers else "auto",
                partition=part_s,
                match_reason="loaded_from_predictions",
                confidence=1.0,
            )
        )

    bib_by_paper: dict[str, list[BibEntry]] = defaultdict(list)
    for bf in _collect_table_files(data_roots, "bibtex"):
        for batch in pq.ParquetFile(bf).iter_batches(batch_size=32768):
            for row in batch.to_pylist():
                pid = str(row["arxiv_id"])
                if pid in selected_papers:
                    bib_by_paper[pid].append(prepare_bib_entry(row))

    refs_by_paper: dict[str, list[RefCandidate]] = defaultdict(list)
    for rf in _collect_table_files(data_roots, "references"):
        for batch in pq.ParquetFile(rf).iter_batches(batch_size=65536):
            for row in batch.to_pylist():
                pid = str(row["arxiv_id"])
                if pid in selected_papers and row.get("ref_arxiv_id"):
                    refs_by_paper[pid].append(prepare_ref_candidate(row))

    # Gộp ngữ cảnh Hierarchy M2 từ tất cả các thư mục nguồn
    hierarchy_context: dict[tuple[str, str], dict[str, Any]] = {}
    for root in data_roots:
        sub_root = (root / "data") if (root / "data" / "elements").is_dir() else root
        if (sub_root / "elements").is_dir() and (sub_root / "hierarchy").is_dir():
            ctx_part = load_m2_citation_context(sub_root, selected_papers)
            hierarchy_context.update(ctx_part)

    return labeled_entries, bib_by_paper, refs_by_paper, hierarchy_context


def compute_metadata_and_year_lag_eda(
    labeled_entries: list[LabeledEntry],
    bib_by_paper: dict[str, list[BibEntry]],
    refs_by_paper: dict[str, list[RefCandidate]],
    hierarchy_context: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Thống kê chất lượng metadata BibTeX, độ phủ ngữ cảnh Hierarchy M2 và phân bố độ trễ năm."""
    bib_lookup = {(b.arxiv_id, b.citation_key): b for items in bib_by_paper.values() for b in items}
    ref_lookup = {(r.arxiv_id, r.ref_arxiv_id): r for items in refs_by_paper.values() for r in items}

    total = len(labeled_entries)
    pos_total = 0
    missing_title = 0
    missing_authors = 0
    missing_year = 0
    missing_doi = 0
    missing_url = 0
    has_explicit_arxiv = 0
    has_hierarchy_ctx = 0
    in_intro_or_related = 0

    year_lag_counter: Counter[int] = Counter()
    year_both_present = 0
    author_count_diffs: list[int] = []
    exact_title_matches = 0
    fuzzy_only_matches = 0

    for e in labeled_entries:
        b = bib_lookup.get((e.arxiv_id, e.citation_key))
        if b is None:
            continue
        if not b.norm_title:
            missing_title += 1
        if not b.parsed_authors:
            missing_authors += 1
        if b.year is None:
            missing_year += 1
        if not b.doi:
            missing_doi += 1
        if not b.url:
            missing_url += 1
        if b.explicit_arxiv_id:
            has_explicit_arxiv += 1
        hctx = hierarchy_context.get((e.arxiv_id, e.citation_key))
        if hctx:
            has_hierarchy_ctx += 1
            if hctx.get("in_intro_or_related", 0.0) > 0:
                in_intro_or_related += 1

        if e.groundtruth_arxiv_id:
            pos_total += 1
            r = ref_lookup.get((e.arxiv_id, e.groundtruth_arxiv_id))
            if r is not None:
                if b.norm_title and b.norm_title == r.norm_title:
                    exact_title_matches += 1
                else:
                    fuzzy_only_matches += 1
                if b.year is not None and r.ref_year is not None:
                    year_both_present += 1
                    lag = max(-3, min(5, b.year - r.ref_year))
                    year_lag_counter[lag] += 1
                if b.parsed_authors and r.parsed_authors:
                    author_count_diffs.append(abs(len(b.parsed_authors) - len(r.parsed_authors)))

    denom = max(1, total)
    pos_denom = max(1, pos_total)
    yr_denom = max(1, year_both_present)

    lag_dist = {
        str(k): {
            "count": int(year_lag_counter.get(k, 0)),
            "pct": round(year_lag_counter.get(k, 0) / yr_denom * 100.0, 2),
        }
        for k in range(-2, 5)
    }

    return {
        "n_entries_analyzed": total,
        "n_positive_entries": pos_total,
        "positive_rate_pct": round(pos_total / denom * 100.0, 2),
        "all_negative_rate_pct": round((total - pos_total) / denom * 100.0, 2),
        "missing_title_pct": round(missing_title / denom * 100.0, 2),
        "missing_authors_pct": round(missing_authors / denom * 100.0, 2),
        "missing_year_pct": round(missing_year / denom * 100.0, 2),
        "missing_doi_pct": round(missing_doi / denom * 100.0, 2),
        "missing_url_pct": round(missing_url / denom * 100.0, 2),
        "has_explicit_arxiv_id_pct": round(has_explicit_arxiv / denom * 100.0, 2),
        "has_m2_hierarchy_ctx_pct": round(has_hierarchy_ctx / denom * 100.0, 2),
        "cited_in_intro_or_related_pct": round(in_intro_or_related / max(1, has_hierarchy_ctx) * 100.0, 2),
        "positive_exact_title_pct": round(exact_title_matches / pos_denom * 100.0, 2),
        "positive_non_exact_title_pct": round(fuzzy_only_matches / pos_denom * 100.0, 2),
        "year_lag_samples": year_both_present,
        "year_lag_distribution": lag_dist,
        "author_count_mismatch_pct": round(
            sum(1 for d in author_count_diffs if d > 0) / max(1, len(author_count_diffs)) * 100.0, 2
        ),
        "mean_author_count_diff": round(float(np.mean(author_count_diffs)) if author_count_diffs else 0.0, 3),
    }


def compute_feature_separation_stats(X: np.ndarray, y: np.ndarray) -> list[dict[str, Any]]:
    """Tính ROC-AUC đơn biến và trung bình/trung vị (Positive vs Negative) cho từng đặc trưng trong 25 đặc trưng."""
    pos_mask = y == 1
    neg_mask = y == 0
    rows: list[dict[str, Any]] = []
    # Các đặc trưng mang hướng "càng nhỏ càng giống" cần đảo dấu khi tính AUC dương
    inverted_features = {
        "author_count_diff",
        "year_abs_diff",
        "title_tfidf_margin_to_best",
        "author_jaccard_margin_to_best",
    }

    for idx, fname in enumerate(FEATURE_NAMES):
        col = X[:, idx].astype(np.float64)
        pos_vals = col[pos_mask]
        neg_vals = col[neg_mask]
        score_col = -col if fname in inverted_features else col
        try:
            auc = float(roc_auc_score(y, score_col))
        except Exception:
            auc = 0.5

        group = (
            "m2_hierarchy_context"
            if fname in HIERARCHY_CONTEXT_FEATURES
            else ("pool_relative" if fname in POOL_RELATIVE_FEATURES else "base_metadata")
        )
        rows.append(
            {
                "feature": fname,
                "group": group,
                "direction": "lower_is_better" if fname in inverted_features else "higher_is_better",
                "roc_auc": round(auc, 4),
                "pos_mean": round(float(np.mean(pos_vals)) if len(pos_vals) else 0.0, 4),
                "neg_mean": round(float(np.mean(neg_vals)) if len(neg_vals) else 0.0, 4),
                "pos_median": round(float(np.median(pos_vals)) if len(pos_vals) else 0.0, 4),
                "neg_median": round(float(np.median(neg_vals)) if len(neg_vals) else 0.0, 4),
                "pos_nonzero_pct": round(float(np.mean(pos_vals != 0)) * 100.0 if len(pos_vals) else 0.0, 2),
                "neg_nonzero_pct": round(float(np.mean(neg_vals != 0)) * 100.0 if len(neg_vals) else 0.0, 2),
            }
        )

    rows.sort(key=lambda r: r["roc_auc"], reverse=True)
    return rows


def _degrade_bib_entry(bib: BibEntry, mode: str) -> BibEntry:
    """Tạo bản sao BibEntry bị nhiễu/khuyết trường để kiểm định áp lực (không ảnh hưởng dữ liệu gốc)."""
    if mode == "S0_clean":
        return bib

    if mode == "S1_no_explicit_id":
        return BibEntry(
            arxiv_id=bib.arxiv_id,
            citation_key=bib.citation_key,
            entry_type=bib.entry_type,
            title=bib.title,
            authors=bib.authors,
            year=bib.year,
            doi="",
            journal=bib.journal,
            url="",
            norm_title=bib.norm_title,
            title_tokens=bib.title_tokens,
            parsed_authors=bib.parsed_authors,
            explicit_arxiv_id=None,
        )

    if mode == "S2_noisy_bbl_title":
        # Giả lập mục .bbl rút gọn tiêu đề (chỉ giữ 40% từ đầu, tối thiểu 2 từ), thiếu arXiv ID và chỉ còn họ tác giả đầu
        words = bib.norm_title.split()
        keep_n = max(2, int(len(words) * 0.40)) if len(words) >= 4 else max(1, len(words) - 1)
        short_title = " ".join(words[:keep_n]) if words else ""
        short_norm = normalize_title(short_title)
        short_toks = frozenset(tokenize_title(short_norm))
        first_only_authors = bib.authors[:1]
        first_only_parsed = bib.parsed_authors[:1]
        return BibEntry(
            arxiv_id=bib.arxiv_id,
            citation_key=bib.citation_key,
            entry_type=bib.entry_type,
            title=short_title,
            authors=first_only_authors,
            year=bib.year,
            doi="",
            journal=bib.journal,
            url="",
            norm_title=short_norm,
            title_tokens=short_toks,
            parsed_authors=first_only_parsed,
            explicit_arxiv_id=None,
        )

    if mode == "S3_missing_title_rescue":
        # Giả lập lỗi tách tiêu đề trong .bbl: mất hoàn toàn tiêu đề & explicit ID, buộc mô hình dựa vào tác giả + năm + cite_key + M2 Hierarchy!
        first_only_authors = bib.authors[:2]
        first_only_parsed = bib.parsed_authors[:2]
        return BibEntry(
            arxiv_id=bib.arxiv_id,
            citation_key=bib.citation_key,
            entry_type=bib.entry_type,
            title="",
            authors=first_only_authors,
            year=bib.year,
            doi="",
            journal=bib.journal,
            url="",
            norm_title="",
            title_tokens=frozenset(),
            parsed_authors=first_only_parsed,
            explicit_arxiv_id=None,
        )

    raise ValueError(f"Unknown degradation mode: {mode}")


def _train_eval_single_model(
    model_name: str,
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    g_tr: np.ndarray,
    X_ev: np.ndarray,
    *,
    seed: int = 42,
    feat_indices: list[int] | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    if feat_indices is not None:
        X_tr_use = X_tr[:, feat_indices]
        X_ev_use = X_ev[:, feat_indices]
    else:
        X_tr_use = X_tr
        X_ev_use = X_ev

    if model_name == "heuristic_baseline":
        # Khi đánh giá trên full 25 features: dùng công thức baseline cổ điển (explicit_id + title_tfidf + author_jaccard)
        scores = (2.0 * X_ev[:, 12] + 1.2 * X_ev[:, 5] + 0.5 * X_ev[:, 8]).astype(np.float32)
        return scores, None

    if model_name == "logistic_regression":
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X_tr_use)
        clf = LogisticRegression(max_iter=300, class_weight="balanced", C=1.0, random_state=seed)
        clf.fit(Xs, y_tr)
        scores = clf.predict_proba(scaler.transform(X_ev_use))[:, 1].astype(np.float32)
        return scores, None

    if model_name == "random_forest":
        rf = RandomForestClassifier(
            n_estimators=80,
            max_depth=12,
            min_samples_leaf=6,
            max_samples=0.4 if len(X_tr_use) > 40_000 else None,
            class_weight="balanced_subsample",
            n_jobs=2,
            random_state=seed,
        )
        rf.fit(X_tr_use, y_tr)
        scores = rf.predict_proba(X_ev_use)[:, 1].astype(np.float32)
        return scores, np.asarray(rf.feature_importances_, dtype=float)

    if model_name == "lightgbm_ranker":
        tr_order = np.argsort(g_tr, kind="mergesort")
        X_tr_s = X_tr_use[tr_order]
        y_tr_s = y_tr[tr_order]
        g_sizes = _group_sizes_from_sorted_queries(g_tr[tr_order])

        ranker = lgb.LGBMRanker(
            objective="lambdarank",
            metric="ndcg",
            n_estimators=120,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=15,
            subsample=0.85,
            colsample_bytree=0.85,
            importance_type="gain",
            random_state=seed,
            n_jobs=2,
            verbose=-1,
        )
        ranker.fit(X_tr_s, y_tr_s, group=g_sizes)
        scores = ranker.predict(X_ev_use).astype(np.float32)
        return scores, np.asarray(ranker.feature_importances_, dtype=float)

    raise ValueError(f"Unknown model: {model_name}")


def run_stress_test_and_manual_cv(
    labeled_entries: list[LabeledEntry],
    bib_by_paper: dict[str, list[BibEntry]],
    refs_by_paper: dict[str, list[RefCandidate]],
    hierarchy_context: dict[tuple[str, str], dict[str, Any]],
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """Đánh giá 4 mô hình + Ablation (A1->A2->A3) trên tập Test chuẩn & 3 kịch bản nhiễu .bbl, kèm 5-fold CV trên 25 bài Manual."""
    # Fit TF-IDF trên tập Train gốc (từ clean titles, giống thực tế khi mô hình triển khai gặp mục .bbl nhiễu lúc inference)
    tfidf = fit_title_tfidf(labeled_entries, bib_by_paper, refs_by_paper)

    ablation_defs = {
        "A1_base_metadata": [FEATURE_NAMES.index(f) for f in BASE_METADATA_FEATURES],
        "A2_plus_pool_relative": [FEATURE_NAMES.index(f) for f in (*BASE_METADATA_FEATURES, *POOL_RELATIVE_FEATURES)],
        "A3_full_with_m2_hierarchy": list(range(len(FEATURE_NAMES))),
    }
    models_order = ["heuristic_baseline", "logistic_regression", "random_forest", "lightgbm_ranker"]
    scenarios = ["S0_clean", "S1_no_explicit_id", "S2_noisy_bbl_title", "S3_missing_title_rescue"]

    scenario_results: dict[str, Any] = {}
    s3_gain_importance: list[dict[str, Any]] = []

    for mode in scenarios:
        t0 = time.perf_counter()
        degraded_bib = {
            pid: [_degrade_bib_entry(b, mode) for b in entries]
            for pid, entries in bib_by_paper.items()
        }
        fb = build_candidate_features(
            labeled_entries,
            degraded_bib,
            refs_by_paper,
            tfidf=tfidf,
            hierarchy_context=hierarchy_context,
        )
        X = fb["X"]
        y = fb["y"]
        groups = fb["groups"]
        part_codes = fb["part_codes"]
        query_meta = fb["query_meta"]
        cand_ref_ids = fb["cand_ref_ids"]
        empty_pool = fb["empty_pool_entries"]

        tr_mask = part_codes == PARTITION_TO_CODE["train"]
        te_mask = part_codes == PARTITION_TO_CODE["test"]
        X_tr, y_tr, g_tr = X[tr_mask], y[tr_mask], groups[tr_mask]

        # Chỉ chấm trên Test queries để nhanh và gọn
        te_groups = groups[te_mask]
        te_cands = [cand_ref_ids[i] for i in np.flatnonzero(te_mask)]
        te_empty = [e for e in empty_pool if e.partition == "test"]
        X_te = X[te_mask]

        mod_res: dict[str, Any] = {}
        for mname in models_order:
            scores_te, imp = _train_eval_single_model(mname, X_tr, y_tr, g_tr, X_te, seed=seed)
            df_te = rank_top5_from_scores(query_meta, te_groups, te_cands, scores_te, te_empty)
            mod_res[mname] = {
                "test": compute_ranking_metrics(df_te),
                "test_manual": compute_ranking_metrics(df_te[df_te["label_source"] == "manual"]),
                "test_auto": compute_ranking_metrics(df_te[df_te["label_source"] == "auto"]),
            }
            if mode == "S3_missing_title_rescue" and mname == "lightgbm_ranker" and imp is not None:
                tot = float(imp.sum()) or 1.0
                for fn, iv in sorted(zip(FEATURE_NAMES, imp), key=lambda kv: kv[1], reverse=True):
                    grp = (
                        "m2_hierarchy_context"
                        if fn in HIERARCHY_CONTEXT_FEATURES
                        else ("pool_relative" if fn in POOL_RELATIVE_FEATURES else "base_metadata")
                    )
                    s3_gain_importance.append(
                        {"feature": fn, "group": grp, "gain_raw": round(float(iv), 3), "gain_share": round(float(iv) / tot, 6)}
                    )

        abl_res: dict[str, Any] = {}
        for abl_name, cols in ablation_defs.items():
            if abl_name == "A3_full_with_m2_hierarchy":
                abl_res[abl_name] = {"n_features": len(cols), "test": mod_res["lightgbm_ranker"]["test"]}
                continue
            sc_abl, _ = _train_eval_single_model("lightgbm_ranker", X_tr, y_tr, g_tr, X_te, seed=seed, feat_indices=cols)
            df_abl = rank_top5_from_scores(query_meta, te_groups, te_cands, sc_abl, te_empty)
            abl_res[abl_name] = {"n_features": len(cols), "test": compute_ranking_metrics(df_abl)}

        scenario_results[mode] = {
            "models": mod_res,
            "ablation": abl_res,
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }
        print(
            f"[m3_analysis] {mode:24s} | "
            + " ".join(
                f"{m[:4]}={mod_res[m]['test']['mrr_at_5']:.4f}({mod_res[m]['test']['recall_at_1']*100:.1f}%)"
                for m in models_order
            )
            + f" | A1={abl_res['A1_base_metadata']['test']['mrr_at_5']:.4f} "
            f"A2={abl_res['A2_plus_pool_relative']['test']['mrr_at_5']:.4f} "
            f"A3={abl_res['A3_full_with_m2_hierarchy']['test']['mrr_at_5']:.4f}",
            flush=True,
        )
        del fb, X, y, degraded_bib
        gc.collect()

    # 5-fold Cross-Validation trên toàn bộ 25 bài Manual (mỗi fold cầm giữ 1 bài của mỗi thành viên -> 5 bài/fold!)
    manual_entries = [e for e in labeled_entries if e.label_source == "manual"]
    manual_by_member: dict[str, list[str]] = defaultdict(list)
    for pid in sorted({e.arxiv_id for e in manual_entries}):
        manual_by_member[assign_member_id(pid)].append(pid)

    cv_results: dict[str, Any] = {}
    for cv_mode in ("S0_clean", "S2_noisy_bbl_title", "S3_missing_title_rescue"):
        degraded_manual_bib = {
            pid: [_degrade_bib_entry(b, cv_mode) for b in bib_by_paper.get(pid, [])]
            for pids in manual_by_member.values()
            for pid in pids
        }
        fb_m = build_candidate_features(
            manual_entries,
            degraded_manual_bib,
            refs_by_paper,
            tfidf=tfidf,
            hierarchy_context=hierarchy_context,
        )
        Xm, ym, gm = fb_m["X"], fb_m["y"], fb_m["groups"]
        qmeta_m = fb_m["query_meta"]
        cands_m = fb_m["cand_ref_ids"]
        paper_per_pair = np.array([qmeta_m[int(q)][0] for q in gm])

        fold_metrics_by_model: dict[str, list[dict[str, float]]] = {m: [] for m in models_order}
        fold_metrics_by_abl: dict[str, list[dict[str, float]]] = {a: [] for a in ablation_defs}

        for fold_idx in range(5):
            val_papers = {pids[fold_idx] for pids in manual_by_member.values() if fold_idx < len(pids)}
            ev_mask = np.isin(paper_per_pair, list(val_papers))
            tr_mask = ~ev_mask
            ev_groups = gm[ev_mask]
            ev_cands = [cands_m[i] for i in np.flatnonzero(ev_mask)]

            for mname in models_order:
                sc_ev, _ = _train_eval_single_model(mname, Xm[tr_mask], ym[tr_mask], gm[tr_mask], Xm[ev_mask], seed=seed + fold_idx)
                df_ev = rank_top5_from_scores(qmeta_m, ev_groups, ev_cands, sc_ev, [])
                fold_metrics_by_model[mname].append(compute_ranking_metrics(df_ev))

            for abl_name, cols in ablation_defs.items():
                if abl_name == "A3_full_with_m2_hierarchy":
                    fold_metrics_by_abl[abl_name].append(fold_metrics_by_model["lightgbm_ranker"][-1])
                    continue
                sc_a, _ = _train_eval_single_model("lightgbm_ranker", Xm[tr_mask], ym[tr_mask], gm[tr_mask], Xm[ev_mask], seed=seed + fold_idx, feat_indices=cols)
                df_a = rank_top5_from_scores(qmeta_m, ev_groups, ev_cands, sc_a, [])
                fold_metrics_by_abl[abl_name].append(compute_ranking_metrics(df_a))

        def _agg(folds: list[dict[str, float]]) -> dict[str, float]:
            return {
                "mrr_at_5_mean": round(float(np.mean([f["mrr_at_5"] for f in folds])), 4),
                "mrr_at_5_std": round(float(np.std([f["mrr_at_5"] for f in folds])), 4),
                "mrr_pos_mean": round(float(np.mean([f["mrr_at_5_positive_only"] for f in folds])), 4),
                "recall_at_1_mean": round(float(np.mean([f["recall_at_1"] for f in folds])), 4),
                "recall_at_5_mean": round(float(np.mean([f["recall_at_5"] for f in folds])), 4),
            }

        cv_results[cv_mode] = {
            "n_manual_papers": sum(len(v) for v in manual_by_member.values()),
            "n_manual_entries": len(manual_entries),
            "models": {m: _agg(v) for m, v in fold_metrics_by_model.items()},
            "ablation": {a: _agg(v) for a, v in fold_metrics_by_abl.items()},
        }
        print(
            f"[m3_cv5]      {cv_mode:24s} | "
            + " ".join(
                f"{m[:4]}={cv_results[cv_mode]['models'][m]['mrr_at_5_mean']:.4f}(R@1={cv_results[cv_mode]['models'][m]['recall_at_1_mean']*100:.1f}%)"
                for m in models_order
            )
            + f" | A1={cv_results[cv_mode]['ablation']['A1_base_metadata']['mrr_at_5_mean']:.4f} "
            f"A2={cv_results[cv_mode]['ablation']['A2_plus_pool_relative']['mrr_at_5_mean']:.4f} "
            f"A3={cv_results[cv_mode]['ablation']['A3_full_with_m2_hierarchy']['mrr_at_5_mean']:.4f}",
            flush=True,
        )

    return {
        "stress_test": scenario_results,
        "manual_5fold_cv": cv_results,
        "s3_lightgbm_gain_importance": s3_gain_importance,
    }


def run_full_feature_eda(
    *,
    data_roots: list[Path],
    manual_labels_path: Path,
    output_json: Path,
    max_train_papers: int = 600,
    seed: int = 42,
) -> dict[str, Any]:
    """Chạy toàn bộ phân tích định lượng đặc trưng, độ trễ năm, ROC-AUC 25 đặc trưng, stress-test và 5-fold CV."""
    t0 = time.perf_counter()
    # Nạp tập đại diện (toàn bộ 35 bài Manual + Valid/Test + max_train_papers bài Train phân tầng) kèm đầy đủ M2 Hierarchy
    labeled_entries, bib_by_paper, refs_by_paper, hierarchy_context = load_labeled_corpus_from_hf_dirs(
        data_roots,
        manual_labels_path,
        max_train_papers=max_train_papers,
        seed=seed,
    )
    print(
        f"[m3_analysis] Loaded {len({e.arxiv_id for e in labeled_entries})} papers, "
        f"{len(labeled_entries):,} entries, {len(hierarchy_context):,} M2 hierarchy keys",
        flush=True,
    )

    meta_eda = compute_metadata_and_year_lag_eda(labeled_entries, bib_by_paper, refs_by_paper, hierarchy_context)

    tfidf = fit_title_tfidf(labeled_entries, bib_by_paper, refs_by_paper)
    fb_clean = build_candidate_features(
        labeled_entries,
        bib_by_paper,
        refs_by_paper,
        tfidf=tfidf,
        hierarchy_context=hierarchy_context,
    )
    feat_sep = compute_feature_separation_stats(fb_clean["X"], fb_clean["y"])
    n_pairs_eda = int(len(fb_clean["y"]))
    n_pos_eda = int(fb_clean["y"].sum())

    # Tính LightGBM Gain importance trên tập clean đầy đủ (120 cây không early-stop ở cây 1)
    tr_mask = fb_clean["part_codes"] == PARTITION_TO_CODE["train"]
    _, lgb_gain_clean = _train_eval_single_model(
        "lightgbm_ranker",
        fb_clean["X"][tr_mask],
        fb_clean["y"][tr_mask],
        fb_clean["groups"][tr_mask],
        fb_clean["X"][:10],
        seed=seed,
    )
    clean_gain_rows: list[dict[str, Any]] = []
    if lgb_gain_clean is not None:
        tot = float(lgb_gain_clean.sum()) or 1.0
        for fn, iv in sorted(zip(FEATURE_NAMES, lgb_gain_clean), key=lambda kv: kv[1], reverse=True):
            grp = (
                "m2_hierarchy_context"
                if fn in HIERARCHY_CONTEXT_FEATURES
                else ("pool_relative" if fn in POOL_RELATIVE_FEATURES else "base_metadata")
            )
            clean_gain_rows.append(
                {"feature": fn, "group": grp, "gain_raw": round(float(iv), 3), "gain_share": round(float(iv) / tot, 6)}
            )

    del fb_clean
    gc.collect()

    stress_and_cv = run_stress_test_and_manual_cv(
        labeled_entries,
        bib_by_paper,
        refs_by_paper,
        hierarchy_context,
        seed=seed,
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "n_papers_analyzed": len({e.arxiv_id for e in labeled_entries}),
        "n_candidate_pairs_analyzed": n_pairs_eda,
        "n_positive_pairs_analyzed": n_pos_eda,
        "metadata_and_year_lag_eda": meta_eda,
        "feature_separation_auc": feat_sep,
        "clean_lightgbm_gain_importance": clean_gain_rows,
        **stress_and_cv,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[m3_analysis] Saved full quantitative EDA report -> {output_json}", flush=True)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run quantitative feature justification EDA, stress-test ablation, and 5-fold manual CV for M3.",
    )
    parser.add_argument(
        "--data-roots",
        nargs="+",
        required=True,
        help="One or more directories holding 6-table HF data/{papers,references,elements,hierarchy,bibtex,predictions}",
    )
    parser.add_argument("--manual-labels", required=True, help="Path to manual_labels.jsonl")
    parser.add_argument("--output", required=True, help="Output JSON path for m3_feature_eda.json")
    parser.add_argument("--max-train-papers", type=int, default=400, help="Stratified train papers cap for fast local EDA")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    run_full_feature_eda(
        data_roots=[Path(p) for p in args.data_roots],
        manual_labels_path=Path(args.manual_labels),
        output_json=Path(args.output),
        max_train_papers=args.max_train_papers,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
