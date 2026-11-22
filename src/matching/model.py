"""Huấn luyện, so sánh mô hình học máy cổ điển, đánh giá MRR@5 và xuất bảng predictions."""
from __future__ import annotations

import gc
import time
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import psutil
import pyarrow as pa
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .features import (
    BASE_METADATA_FEATURES,
    FEATURE_NAMES,
    HIERARCHY_CONTEXT_FEATURES,
    PARTITION_TO_CODE,
    POOL_RELATIVE_FEATURES,
)
from .labeling import LabeledEntry

PARTITION_DICTIONARY = pa.dictionary(pa.int32(), pa.string())
PREDICTIONS_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("partition", PARTITION_DICTIONARY, nullable=False),
    pa.field("citation_key", pa.string(), nullable=False),
    pa.field("groundtruth_arxiv_id", pa.string(), nullable=True),
    pa.field("cand_1", pa.string(), nullable=True),
    pa.field("cand_2", pa.string(), nullable=True),
    pa.field("cand_3", pa.string(), nullable=True),
    pa.field("cand_4", pa.string(), nullable=True),
    pa.field("cand_5", pa.string(), nullable=True),
])


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 ** 2)


def rank_top5_from_scores(
    query_meta: list[tuple[str, str, str, str, str | None]],
    query_ids: np.ndarray,
    cand_ref_ids: list[str],
    scores: np.ndarray,
    empty_pool_entries: list[LabeledEntry] | None = None,
) -> pd.DataFrame:
    """Gom cặp ứng viên (đã sắp liên tục theo query_id) thành top-5 cand_1..cand_5."""
    rows: list[dict[str, Any]] = []
    n_total = len(query_ids)
    start = 0
    while start < n_total:
        qid = int(query_ids[start])
        end = start + 1
        while end < n_total and int(query_ids[end]) == qid:
            end += 1

        arxiv_id, partition, label_source, citation_key, gt_id = query_meta[qid]
        sub_scores = scores[start:end]
        k = min(5, end - start)
        # Lấy top-k nhanh theo thứ tự giảm dần score, phá hòa bằng ref_arxiv_id tăng dần
        order = sorted(
            range(start, end),
            key=lambda idx: (-float(scores[idx]), cand_ref_ids[idx]),
        )
        top5 = [cand_ref_ids[idx] for idx in order[:k]]
        while len(top5) < 5:
            top5.append(None)

        rows.append({
            "arxiv_id": arxiv_id,
            "partition": partition,
            "label_source": label_source,
            "citation_key": citation_key,
            "groundtruth_arxiv_id": gt_id,
            "cand_1": top5[0],
            "cand_2": top5[1],
            "cand_3": top5[2],
            "cand_4": top5[3],
            "cand_5": top5[4],
        })
        start = end

    for entry in (empty_pool_entries or []):
        rows.append({
            "arxiv_id": entry.arxiv_id,
            "partition": entry.partition,
            "label_source": entry.label_source,
            "citation_key": entry.citation_key,
            "groundtruth_arxiv_id": entry.groundtruth_arxiv_id,
            "cand_1": None,
            "cand_2": None,
            "cand_3": None,
            "cand_4": None,
            "cand_5": None,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["partition", "arxiv_id", "citation_key"]).reset_index(drop=True)
    return df


def compute_ranking_metrics(df_preds: pd.DataFrame) -> dict[str, float | int]:
    """Tính chính xác MRR@5 (theo công thức đề trên toàn tập |Q|), Recall@1 và Recall@5."""
    n = len(df_preds)
    if n == 0:
        return {
            "n_entries": 0,
            "n_positive_entries": 0,
            "mrr_at_5": 0.0,
            "mrr_at_5_positive_only": 0.0,
            "recall_at_1": 0.0,
            "recall_at_5": 0.0,
        }

    rr_sum = 0.0
    r1 = 0
    r5 = 0
    n_pos = 0
    for row in df_preds.itertuples(index=False):
        gt = row.groundtruth_arxiv_id
        if not gt:
            continue
        n_pos += 1
        cands = (row.cand_1, row.cand_2, row.cand_3, row.cand_4, row.cand_5)
        for rank_idx, cid in enumerate(cands, start=1):
            if cid == gt:
                rr_sum += 1.0 / rank_idx
                if rank_idx == 1:
                    r1 += 1
                r5 += 1
                break

    return {
        "n_entries": int(n),
        "n_positive_entries": int(n_pos),
        "mrr_at_5": round(rr_sum / n, 6),
        "mrr_at_5_positive_only": round(rr_sum / n_pos, 6) if n_pos > 0 else 0.0,
        "recall_at_1": round(r1 / n_pos, 6) if n_pos > 0 else 0.0,
        "recall_at_5": round(r5 / n_pos, 6) if n_pos > 0 else 0.0,
    }


def _evaluate_split_breakdown(df_preds: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    for part in ("train", "valid", "test"):
        sub = df_preds[df_preds["partition"] == part]
        out[part] = compute_ranking_metrics(sub)
    test_sub = df_preds[df_preds["partition"] == "test"]
    out["test_manual"] = compute_ranking_metrics(test_sub[test_sub["label_source"] == "manual"])
    out["test_auto"] = compute_ranking_metrics(test_sub[test_sub["label_source"] == "auto"])
    valid_sub = df_preds[df_preds["partition"] == "valid"]
    out["valid_manual"] = compute_ranking_metrics(valid_sub[valid_sub["label_source"] == "manual"])
    out["valid_auto"] = compute_ranking_metrics(valid_sub[valid_sub["label_source"] == "auto"])
    return out


def _group_sizes_from_sorted_queries(query_ids: np.ndarray) -> list[int]:
    if len(query_ids) == 0:
        return []
    _, counts = np.unique(query_ids, return_counts=True)
    return [int(c) for c in counts]


def _predict_in_chunks(model_fn, X: np.ndarray, chunk_size: int = 250_000) -> np.ndarray:
    out = np.empty(len(X), dtype=np.float32)
    for s in range(0, len(X), chunk_size):
        e = min(len(X), s + chunk_size)
        out[s:e] = model_fn(X[s:e])
    return out


def _fit_and_score_model(
    model_name: str,
    X_train: np.ndarray,
    y_train: np.ndarray,
    groups_train: np.ndarray,
    X_eval: np.ndarray,
    X_valid: np.ndarray | None = None,
    y_valid: np.ndarray | None = None,
    groups_valid: np.ndarray | None = None,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Huấn luyện 1 mô hình và trả về (scores, feature_importances_or_None) để giải phóng model ngay."""
    if model_name == "heuristic_baseline":
        scores = (2.0 * X_eval[:, 12] + 1.2 * X_eval[:, 5] + 0.5 * X_eval[:, 8]).astype(np.float32)
        return scores, None

    if model_name == "logistic_regression":
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X_train)
        clf = LogisticRegression(max_iter=300, class_weight="balanced", C=1.0, random_state=seed)
        clf.fit(Xs, y_train)
        del Xs
        gc.collect()
        scores = _predict_in_chunks(lambda chunk: clf.predict_proba(scaler.transform(chunk))[:, 1], X_eval)
        return scores, None

    if model_name == "random_forest":
        rf = RandomForestClassifier(
            n_estimators=60,
            max_depth=12,
            min_samples_leaf=8,
            max_samples=0.25 if len(X_train) > 50_000 else None,
            class_weight="balanced_subsample",
            n_jobs=1,
            random_state=seed,
        )
        rf.fit(X_train, y_train)
        scores = _predict_in_chunks(lambda chunk: rf.predict_proba(chunk)[:, 1], X_eval)
        imp = np.asarray(rf.feature_importances_, dtype=float)
        del rf
        gc.collect()
        return scores, imp

    if model_name == "lightgbm_ranker":
        # query_ids đã tăng dần sẵn theo vòng lặp build_candidate_features; kiểm tra trước khi sort
        if len(groups_train) > 1 and np.any(groups_train[1:] < groups_train[:-1]):
            tr_order = np.argsort(groups_train, kind="mergesort")
            X_tr_sorted = X_train[tr_order]
            y_tr_sorted = y_train[tr_order]
            g_tr_sizes = _group_sizes_from_sorted_queries(groups_train[tr_order])
        else:
            X_tr_sorted = X_train
            y_tr_sorted = y_train
            g_tr_sizes = _group_sizes_from_sorted_queries(groups_train)

        ranker = lgb.LGBMRanker(
            objective="lambdarank",
            metric="ndcg",
            ndcg_eval_at=[1, 5],
            n_estimators=220,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.85,
            colsample_bytree=0.85,
            random_state=seed,
            n_jobs=2,
            verbose=-1,
        )
        fit_kwargs: dict[str, Any] = {"group": g_tr_sizes}
        if X_valid is not None and y_valid is not None and groups_valid is not None and len(X_valid) > 0:
            va_order = np.argsort(groups_valid, kind="mergesort")
            fit_kwargs["eval_set"] = [(X_valid[va_order], y_valid[va_order])]
            fit_kwargs["eval_group"] = [_group_sizes_from_sorted_queries(groups_valid[va_order])]
            fit_kwargs["callbacks"] = [lgb.early_stopping(stopping_rounds=25, verbose=False)]

        ranker.fit(X_tr_sorted, y_tr_sorted, **fit_kwargs)
        scores = _predict_in_chunks(ranker.predict, X_eval)
        imp = np.asarray(ranker.feature_importances_, dtype=float)
        del ranker
        gc.collect()
        return scores, imp

    raise ValueError(f"Unknown model_name: {model_name}")


def run_matching_models(
    feature_bundle: dict[str, Any],
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """Chạy so sánh 4 mô hình cổ điển, chọn mô hình tốt nhất theo Validation MRR@5 và chạy Ablation Study."""
    X = feature_bundle["X"]
    y = feature_bundle["y"]
    groups = feature_bundle["groups"]
    part_codes = feature_bundle["part_codes"]
    query_meta = feature_bundle["query_meta"]
    cand_ref_ids = feature_bundle["cand_ref_ids"]
    empty_pool_entries = feature_bundle["empty_pool_entries"]

    if len(X) == 0:
        raise ValueError("Empty candidate feature matrix; cannot train matching models")

    tr_mask = part_codes == PARTITION_TO_CODE["train"]
    va_mask = part_codes == PARTITION_TO_CODE["valid"]

    X_tr, y_tr, g_tr = X[tr_mask], y[tr_mask], groups[tr_mask]
    X_va, y_va, g_va = X[va_mask], y[va_mask], groups[va_mask]

    model_names = [
        "heuristic_baseline",
        "logistic_regression",
        "random_forest",
        "lightgbm_ranker",
    ]

    model_results: dict[str, dict[str, Any]] = {}
    best_name: str | None = None
    best_valid_mrr = -1.0
    best_preds_df: pd.DataFrame | None = None
    lgb_importance: np.ndarray | None = None

    for name in model_names:
        t0 = time.perf_counter()
        scores, imp = _fit_and_score_model(
            name,
            X_tr,
            y_tr,
            g_tr,
            X,
            X_valid=X_va,
            y_valid=y_va,
            groups_valid=g_va,
            seed=seed,
        )
        preds_df = rank_top5_from_scores(query_meta, groups, cand_ref_ids, scores, empty_pool_entries)
        metrics = _evaluate_split_breakdown(preds_df)
        model_results[name] = metrics
        if name == "lightgbm_ranker" and imp is not None:
            lgb_importance = imp
        print(
            f"[m3_model] {name}: valid_MRR@5={metrics['valid']['mrr_at_5']:.4f} "
            f"test_MRR@5={metrics['test']['mrr_at_5']:.4f} "
            f"test_R@1={metrics['test']['recall_at_1']:.4f} "
            f"({time.perf_counter() - t0:.1f}s, rss={_rss_mb():.0f} MiB)",
            flush=True,
        )
        val_mrr = metrics["valid"]["mrr_at_5"]
        if val_mrr > best_valid_mrr or (val_mrr == best_valid_mrr and name == "lightgbm_ranker"):
            best_valid_mrr = val_mrr
            best_name = name
            best_preds_df = preds_df
        del scores
        gc.collect()

    importance_rows: list[dict[str, Any]] = []
    if lgb_importance is not None:
        total_imp = float(lgb_importance.sum()) or 1.0
        for fname, val in sorted(zip(FEATURE_NAMES, lgb_importance), key=lambda kv: kv[1], reverse=True):
            group = (
                "m2_hierarchy_context" if fname in HIERARCHY_CONTEXT_FEATURES
                else ("pool_relative" if fname in POOL_RELATIVE_FEATURES else "base_metadata")
            )
            importance_rows.append({
                "feature": fname,
                "group": group,
                "importance_raw": float(val),
                "importance_share": round(float(val) / total_imp, 6),
            })

    # Ablation Study trên kiến trúc LightGBM Ranker
    ablation_configs = [
        ("A1_base_metadata", list(BASE_METADATA_FEATURES)),
        ("A2_plus_pool_relative", [*BASE_METADATA_FEATURES, *POOL_RELATIVE_FEATURES]),
        ("A3_full_with_m2_hierarchy", list(FEATURE_NAMES)),
    ]
    ablation_results: dict[str, Any] = {}
    for abl_name, feat_subset in ablation_configs:
        if abl_name == "A3_full_with_m2_hierarchy":
            ablation_results[abl_name] = {
                "n_features": len(feat_subset),
                "metrics": model_results["lightgbm_ranker"],
            }
            continue
        cols = [FEATURE_NAMES.index(f) for f in feat_subset]
        scores_abl, _ = _fit_and_score_model(
            "lightgbm_ranker",
            X_tr[:, cols],
            y_tr,
            g_tr,
            X[:, cols],
            X_valid=X_va[:, cols],
            y_valid=y_va,
            groups_valid=g_va,
            seed=seed,
        )
        df_abl = rank_top5_from_scores(query_meta, groups, cand_ref_ids, scores_abl, empty_pool_entries)
        ablation_results[abl_name] = {
            "n_features": len(cols),
            "metrics": _evaluate_split_breakdown(df_abl),
        }
        print(
            f"[m3_ablation] {abl_name} ({len(cols)} feats): "
            f"test_MRR@5={ablation_results[abl_name]['metrics']['test']['mrr_at_5']:.4f} "
            f"(rss={_rss_mb():.0f} MiB)",
            flush=True,
        )
        del scores_abl, df_abl
        gc.collect()

    assert best_preds_df is not None and best_name is not None
    test_misses = best_preds_df[
        (best_preds_df["partition"] == "test")
        & (best_preds_df["groundtruth_arxiv_id"].notna())
        & (best_preds_df["cand_1"] != best_preds_df["groundtruth_arxiv_id"])
    ]
    miss_examples = []
    for row in test_misses.head(15).itertuples(index=False):
        cands = (row.cand_1, row.cand_2, row.cand_3, row.cand_4, row.cand_5)
        rank_pos = next((idx for idx, c in enumerate(cands, 1) if c == row.groundtruth_arxiv_id), None)
        miss_examples.append({
            "arxiv_id": row.arxiv_id,
            "citation_key": row.citation_key,
            "label_source": row.label_source,
            "groundtruth_arxiv_id": row.groundtruth_arxiv_id,
            "rank_in_top5": rank_pos,
            "cand_1": row.cand_1,
            "cand_2": row.cand_2,
        })

    return {
        "best_model": best_name,
        "models": model_results,
        "ablation": ablation_results,
        "feature_importance": importance_rows,
        "error_analysis": {
            "test_positive_not_rank1": int(len(test_misses)),
            "sample_misses": miss_examples,
        },
        "predictions_df": best_preds_df,
    }


def build_predictions_arrow_table(df_preds: pd.DataFrame) -> pa.Table:
    """Chuyển DataFrame kết quả sang PyArrow Table khớp schema predictions chính thức."""
    cols = ["arxiv_id", "partition", "citation_key", "groundtruth_arxiv_id", "cand_1", "cand_2", "cand_3", "cand_4", "cand_5"]
    if df_preds.empty:
        return PREDICTIONS_SCHEMA.empty_table()
    records = [
        {
            col: (None if (val is None or pd.isna(val)) else str(val))
            for col, val in zip(cols, row)
        }
        for row in df_preds[cols].itertuples(index=False, name=None)
    ]
    return pa.Table.from_pylist(records, schema=PREDICTIONS_SCHEMA)
