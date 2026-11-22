"""Milestone 3 — Reference Matching Pipeline (Classical ML).

Liên kết các mục BibTeX chuẩn hóa từ Milestone 2 với metadata trích dẫn arXiv
thu thập ở Milestone 1 bằng các đặc trưng văn bản, tác giả, thời gian và ngữ cảnh
cây phân cấp (hierarchy) của Milestone 2.
"""
from __future__ import annotations

from .cleaning import (
    extract_arxiv_id,
    extract_year,
    normalize_title,
    parse_author_surnames,
    strip_latex,
    tokenize_title,
)
from .features import FEATURE_NAMES, build_candidate_features
from .labeling import (
    MEMBER_RANGES,
    assign_member_id,
    build_labeled_dataset,
)
from .model import (
    PREDICTIONS_SCHEMA,
    compute_ranking_metrics,
    run_matching_models,
)
from .pipeline import run_pipeline

__all__ = [
    "FEATURE_NAMES",
    "MEMBER_RANGES",
    "PREDICTIONS_SCHEMA",
    "assign_member_id",
    "build_candidate_features",
    "build_labeled_dataset",
    "compute_ranking_metrics",
    "extract_arxiv_id",
    "extract_year",
    "normalize_title",
    "parse_author_surnames",
    "run_matching_models",
    "run_pipeline",
    "strip_latex",
    "tokenize_title",
]
