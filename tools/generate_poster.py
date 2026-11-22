"""Sinh Poster học thuật 1 trang khổ đứng A2 (420mm x 594mm) bằng tiếng Việt từ số liệu thực M1-M3 & EDA."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
from matplotlib.patches import Patch
import matplotlib.pyplot as plt
import numpy as np
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

# Kích thước chuẩn khổ đứng A2: 420 mm x 594 mm
A2_WIDTH_IN = 420.0 / 25.4   # 16.5354 in
A2_HEIGHT_IN = 594.0 / 25.4  # 23.3858 in

NAVY = RGBColor(0x0F, 0x27, 0x44)
SLATE_BG = RGBColor(0xF1, 0xF5, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SKY = RGBColor(0x02, 0x84, 0xC7)
SKY_LIGHT = RGBColor(0x7D, 0xD3, 0xFC)
TEAL = RGBColor(0x0D, 0x94, 0x88)
AMBER = RGBColor(0xD9, 0x77, 0x06)
TEXT_DARK = RGBColor(0x1E, 0x29, 0x3B)
TEXT_MUTED = RGBColor(0x47, 0x55, 0x69)
BORDER = RGBColor(0xCB, 0xD5, 0xE1)
CARD_TINT = RGBColor(0xEC, 0xF8, 0xFF)

FONT_NAME = "DejaVu Sans"

MODEL_LABELS = {
    "heuristic_baseline": "Heuristic\nBaseline",
    "logistic_regression": "Logistic\nRegression",
    "random_forest": "Random\nForest",
    "lightgbm_ranker": "LightGBM\nRanker",
}

MODEL_SHORT = {
    "heuristic_baseline": "Heuristic Baseline",
    "logistic_regression": "Logistic Regression",
    "random_forest": "Random Forest",
    "lightgbm_ranker": "LightGBM Ranker",
}

FEATURE_VI_LABELS = {
    "arxiv_id_exact_match": "Khớp trực tiếp arXiv ID (100% precision)",
    "title_tfidf_cosine": "TF-IDF Cosine tiêu đề (1–2 gram)",
    "title_rapidfuzz_ratio": "Tương đồng chuỗi tiêu đề (Fuzzy)",
    "title_token_jaccard": "Jaccard token tiêu đề",
    "title_token_dice": "Dice token tiêu đề",
    "title_containment_bib_in_ref": "Độ bao phủ token tiêu đề",
    "title_exact_norm": "Khớp chính xác tiêu đề chuẩn hóa",
    "title_len_ratio": "Tỷ lệ độ dài tiêu đề",
    "first_author_surname_match": "Khớp họ tác giả đầu",
    "author_surname_jaccard": "Jaccard họ tác giả",
    "author_surname_recall": "Recall họ tác giả (bền với et al.)",
    "author_initial_surname_match": "Khớp (Họ + chữ đầu tên)",
    "author_count_diff": "Chênh lệch số tác giả",
    "year_exact_match": "Khớp chính xác năm",
    "year_abs_diff": "Độ lệch tuyệt đối năm",
    "year_diff_signed": "Độ trễ năm arXiv ↔ xuất bản",
    "cite_key_author_year_hit": "Gợi ý họ + năm từ citation_key",
    "title_tfidf_margin_to_best": "[Pool] Khoảng cách tới TF-IDF tốt nhất",
    "title_tfidf_rank_inv": "[Pool] Hạng nghịch đảo TF-IDF",
    "author_jaccard_margin_to_best": "[Pool] Khoảng cách tới tác giả tốt nhất",
    "pool_size_log": "[Pool] Kích thước tập ứng viên (log)",
    "hier_cite_count": "[M2 Hierarchy] Tần suất \\cite{}",
    "hier_in_intro_or_related": "[M2 Hierarchy] Thuộc Intro/Related",
    "hier_context_title_tfidf_cosine": "[M2 Hierarchy] Câu trích dẫn ↔ tiêu đề",
    "hier_context_author_hit": "[M2 Hierarchy] Họ tác giả trong câu \\cite{}",
}


def _setup_plt() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": "#94A3B8",
        "axes.linewidth": 0.9,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.dpi": 300,
    })


def render_charts(
    m2_summary: dict[str, Any],
    m3_summary: dict[str, Any],
    feat_imp: list[dict[str, Any]],
    ablation: dict[str, Any],
    charts_dir: Path,
    feature_eda: dict[str, Any] | None = None,
) -> dict[str, Path]:
    _setup_plt()
    charts_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # 1. Biểu đồ M1-M2: Trạng thái parse 41.498 version & Khử trùng 2 tầng
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.15), gridspec_kw={"width_ratios": [1.15, 1.0]})
    sc = m2_summary["m2_status_counts"]
    st_labels = ["Thành công\n(success)", "Bán phần\n(partial)", "Không có TeX\n(empty)", "Lỗi parse\n(error)", "Thiếu nguồn\n(404/pending)"]
    st_vals = [
        sc.get("success", 0),
        sc.get("partial", 0),
        sc.get("empty_no_tex", 0),
        sc.get("error", 0),
        sc.get("error_missing_source", 0),
    ]
    st_colors = ["#0284C7", "#38BDF8", "#94A3B8", "#F59E0B", "#EF4444"]
    y_pos = np.arange(len(st_labels))
    bars = ax1.barh(y_pos, st_vals, color=st_colors, height=0.62)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(st_labels, fontsize=9.3, color="#1E293B")
    ax1.invert_yaxis()
    ax1.set_title("Trạng thái phân tích 41.498 phiên bản (M2)", fontsize=10.8, fontweight="bold", color="#0F2744", pad=9)
    ax1.set_xlabel("Số phiên bản", fontsize=9.2, color="#334155")
    ax1.set_xlim(0, max(st_vals) * 1.24)
    for b, v in zip(bars, st_vals):
        ax1.text(v + max(st_vals) * 0.02, b.get_y() + b.get_height() / 2, f"{v:,}", va="center", fontsize=8.8, fontweight="bold", color="#0F172A")

    dd = m2_summary["m2_deduplication"]
    cats = ["Elements\n(triệu dòng)", "BibTeX\n(triệu dòng)"]
    before_m = [dd["elements"]["before"] / 1e6, dd["bibtex"]["before"] / 1e6]
    after_m = [dd["elements"]["after"] / 1e6, dd["bibtex"]["after"] / 1e6]
    rates = [dd["elements"]["reduction_rate"] * 100, dd["bibtex"]["reduction_rate"] * 100]
    x = np.arange(len(cats))
    w = 0.34
    ax2.bar(x - w / 2, before_m, w, label="Trước khử trùng", color="#94A3B8")
    ax2.bar(x + w / 2, after_m, w, label="Sau khử trùng", color="#0D9488")
    ax2.set_xticks(x)
    ax2.set_xticklabels(cats, fontsize=9.3, color="#1E293B")
    ax2.set_title("Hiệu quả khử trùng 2 tầng xuyên phiên bản", fontsize=10.8, fontweight="bold", color="#0F2744", pad=9)
    ax2.set_ylabel("Triệu bản ghi", fontsize=9.2, color="#334155")
    ax2.set_ylim(0, max(before_m) * 1.26)
    ax2.legend(frameon=False, fontsize=8.8, loc="upper right")
    for idx_c in range(len(cats)):
        ax2.text(x[idx_c] - w / 2, before_m[idx_c] + 0.45, f"{before_m[idx_c]:.2f}M", ha="center", fontsize=8.5, color="#475569")
        ax2.text(x[idx_c] + w / 2, after_m[idx_c] + 0.45, f"{after_m[idx_c]:.2f}M\n(-{rates[idx_c]:.1f}%)", ha="center", fontsize=8.5, fontweight="bold", color="#0F766E")

    fig.tight_layout(pad=1.2)
    p1 = charts_dir / "chart_m1_m2_overview.png"
    fig.savefig(p1)
    plt.close(fig)
    paths["m1_m2"] = p1

    # 2. Biểu đồ so sánh 4 mô hình cổ điển: Test chuẩn (S0) vs Kịch bản nhiễu .bbl (S2 & S3)
    models_order = ["heuristic_baseline", "logistic_regression", "random_forest", "lightgbm_ranker"]
    labels = [MODEL_LABELS[m] for m in models_order]
    fig, ax = plt.subplots(figsize=(10.2, 3.85))
    x = np.arange(len(models_order))
    w = 0.25

    if feature_eda and "stress_test" in feature_eda:
        st = feature_eda["stress_test"]
        s0_vals = [st["S0_clean"]["models"][m]["test"]["mrr_at_5"] for m in models_order]
        s2_vals = [st["S2_noisy_bbl_title"]["models"][m]["test"]["mrr_at_5"] for m in models_order]
        s3_vals = [st["S3_missing_title_rescue"]["models"][m]["test"]["mrr_at_5"] for m in models_order]

        b0 = ax.bar(x - w, s0_vals, w, label="Test chuẩn S0 (trần 0,6907)", color="#0F2744")
        b2 = ax.bar(x, s2_vals, w, label="Test S2: Rút gọn tiêu đề .bbl", color="#0284C7")
        b3 = ax.bar(x + w, s3_vals, w, label="Test S3: Khuyết hoàn toàn tiêu đề", color="#D97706")

        ax.axhline(0.690741, color="#0D9488", linestyle=":", linewidth=1.25, alpha=0.9)
        ax.text(0.45, 0.718, "Trần lý thuyết: 373/540 = 0,6907", fontsize=7.9, color="#0F766E", ha="center", fontweight="bold")
        ax.set_ylim(0.54, 0.775)
        ax.set_yticks([0.55, 0.60, 0.65, 0.70])
        ax.set_ylabel("Test MRR@5 (|Q| = 540)", fontsize=9.3, color="#334155")
        ax.set_title("So sánh 4 mô hình cổ điển: Test chuẩn (S0) vs Stress-Test .bbl nhiễu/khuyết (S2, S3)", fontsize=10.5, fontweight="bold", color="#0F2744", pad=16)
        ax.legend(frameon=False, fontsize=8.4, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.05))
        for group_bars in (b0, b2, b3):
            for b in group_bars:
                v = b.get_height()
                ax.text(b.get_x() + b.get_width() / 2, v + 0.004, f"{v:.4f}", ha="center", va="bottom", fontsize=7.9, fontweight="bold", color="#0F172A")
    else:
        mrr_all = [m3_summary["models"][m]["test"]["mrr_at_5"] for m in models_order]
        r1_vals = [m3_summary["models"][m]["test"]["recall_at_1"] for m in models_order]
        r5_vals = [m3_summary["models"][m]["test"]["recall_at_5"] for m in models_order]
        b0 = ax.bar(x - w, mrr_all, w, label="Test MRR@5 (toàn bộ |Q|)", color="#0F2744")
        b2 = ax.bar(x, r1_vals, w, label="Test Recall@1 (mục có đích)", color="#0284C7")
        b3 = ax.bar(x + w, r5_vals, w, label="Test Recall@5 (mục có đích)", color="#0D9488")
        ax.set_ylim(0, 1.26)
        ax.set_ylabel("Điểm đánh giá", fontsize=9.3, color="#334155")
        ax.set_title("So sánh 4 mô hình cổ điển trên tập Test (5 bài Manual + 5 bài Auto)", fontsize=10.8, fontweight="bold", color="#0F2744", pad=16)
        ax.legend(frameon=False, fontsize=8.6, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.04))
        for group_bars in (b0, b2, b3):
            for b in group_bars:
                v = b.get_height()
                ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.3f}", ha="center", va="bottom", fontsize=8.1, fontweight="bold", color="#0F172A")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.3, fontweight="bold", color="#1E293B")
    ax.grid(axis="y", linestyle="--", alpha=0.35, color="#CBD5E1")
    ax.set_axisbelow(True)
    fig.tight_layout(pad=1.0)
    p2 = charts_dir / "chart_m3_models.png"
    fig.savefig(p2)
    plt.close(fig)
    paths["models"] = p2

    # 3. Biểu đồ giải thích đặc trưng bằng dữ liệu thật: ROC-AUC đơn biến trên 1,12 triệu cặp (đủ cả 5 nhóm!)
    fig, ax = plt.subplots(figsize=(10.2, 4.35))
    color_map = {
        "base_metadata": "#0284C7",
        "pool_relative": "#0D9488",
        "m2_hierarchy_context": "#D97706",
    }
    if feature_eda and "feature_separation_auc" in feature_eda:
        auc_by_name = {item["feature"]: item for item in feature_eda["feature_separation_auc"]}
        # Chọn 12 đặc trưng đại diện rõ nhất cho đủ cả 5 nhóm (Tiêu đề, Tác giả, Thời gian/ID, Pool, Hierarchy M2)
        showcase = [
            "title_token_jaccard",
            "title_tfidf_cosine",
            "author_surname_recall",
            "title_tfidf_rank_inv",
            "first_author_surname_match",
            "cite_key_author_year_hit",
            "title_tfidf_margin_to_best",
            "year_abs_diff",
            "author_jaccard_margin_to_best",
            "hier_context_author_hit",
            "year_exact_match",
            "hier_context_title_tfidf_cosine",
        ]
        items = [auc_by_name[f] for f in showcase if f in auc_by_name]
        f_labels = [FEATURE_VI_LABELS.get(it["feature"], it["feature"]) for it in items]
        f_vals = [it["roc_auc"] for it in items]
        f_colors = [color_map.get(it["group"], "#64748B") for it in items]
        y_pos = np.arange(len(f_labels))
        bars = ax.barh(y_pos, f_vals, color=f_colors, height=0.66)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(f_labels, fontsize=8.8, color="#1E293B")
        ax.invert_yaxis()
        ax.set_xlim(0.50, 1.08)
        ax.axvline(0.50, color="#94A3B8", linestyle="--", linewidth=0.8)
        ax.set_xlabel("ROC-AUC đơn biến (Phân tách cặp Dương vs Âm trên 1,12 triệu cặp thật)", fontsize=9.0, color="#334155")
        ax.set_title("Đánh giá định lượng sức phân tách đặc trưng theo 5 nhóm (EDA thực nghiệm)", fontsize=10.6, fontweight="bold", color="#0F2744", pad=10)
        for b, v in zip(bars, f_vals):
            ax.text(v + 0.008, b.get_y() + b.get_height() / 2, f"{v:.4f}", va="center", fontsize=8.3, fontweight="bold", color="#0F172A")
    else:
        nonzero_imp = [item for item in feat_imp if item["importance_raw"] > 0]
        top_feats = nonzero_imp[:12] if len(nonzero_imp) >= 12 else feat_imp[:12]
        f_labels = [FEATURE_VI_LABELS.get(item["feature"], item["feature"]) for item in top_feats]
        f_vals = [item["importance_share"] * 100.0 for item in top_feats]
        f_colors = [color_map.get(item["group"], "#64748B") for item in top_feats]
        y_pos = np.arange(len(f_labels))
        bars = ax.barh(y_pos, f_vals, color=f_colors, height=0.66)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(f_labels, fontsize=8.8, color="#1E293B")
        ax.invert_yaxis()
        ax.set_xlabel("Tỷ trọng độ quan trọng đặc trưng (%)", fontsize=9.2, color="#334155")
        ax.set_title("Top-12 đặc trưng quan trọng nhất (LightGBM Ranker)", fontsize=10.8, fontweight="bold", color="#0F2744", pad=10)
        ax.set_xlim(0, max(f_vals) * 1.22 if f_vals else 10)
        for b, v in zip(bars, f_vals):
            ax.text(v + (max(f_vals) * 0.018 if f_vals else 0.2), b.get_y() + b.get_height() / 2, f"{v:.1f}%", va="center", fontsize=8.5, fontweight="bold", color="#0F172A")

    legend_handles = [
        Patch(facecolor="#0284C7", label="Metadata cơ bản (Tiêu đề/Tác giả/Năm/ID)"),
        Patch(facecolor="#0D9488", label="Tương đối trong Pool ứng viên"),
        Patch(facecolor="#D97706", label="Ngữ cảnh cây Hierarchy M2"),
    ]
    ax.legend(handles=legend_handles, frameon=False, fontsize=8.1, loc="lower right")
    fig.tight_layout(pad=1.0)
    p3 = charts_dir / "chart_m3_features.png"
    fig.savefig(p3)
    plt.close(fig)
    paths["features"] = p3

    # 4. Biểu đồ Ablation Study (A1 -> A2 -> A3) trên 5-Fold Manual CV (25 bài, 1.150 mục) ở kịch bản khuyết tiêu đề S3
    fig, ax = plt.subplots(figsize=(10.2, 2.95))
    if feature_eda and "manual_5fold_cv" in feature_eda:
        cv_s3 = feature_eda["manual_5fold_cv"]["S3_missing_title_rescue"]
        cats = [
            "Heuristic\nBaseline",
            "A1: Metadata\n(17 đặc trưng)",
            "A2: + Pool\n(21 đặc trưng)",
            "A3: + Hierarchy M2\n(đủ 25 đặc trưng)",
        ]
        mrr_vals = [
            cv_s3["models"]["heuristic_baseline"]["mrr_at_5_mean"],
            cv_s3["ablation"]["A1_base_metadata"]["mrr_at_5_mean"],
            cv_s3["ablation"]["A2_plus_pool_relative"]["mrr_at_5_mean"],
            cv_s3["ablation"]["A3_full_with_m2_hierarchy"]["mrr_at_5_mean"],
        ]
        pos_mrr_vals = [
            cv_s3["models"]["heuristic_baseline"]["mrr_pos_mean"],
            cv_s3["ablation"]["A1_base_metadata"]["mrr_pos_mean"],
            cv_s3["ablation"]["A2_plus_pool_relative"]["mrr_pos_mean"],
            cv_s3["ablation"]["A3_full_with_m2_hierarchy"]["mrr_pos_mean"],
        ]
        r1_vals = [
            cv_s3["models"]["heuristic_baseline"]["recall_at_1_mean"],
            cv_s3["ablation"]["A1_base_metadata"]["recall_at_1_mean"],
            cv_s3["ablation"]["A2_plus_pool_relative"]["recall_at_1_mean"],
            cv_s3["ablation"]["A3_full_with_m2_hierarchy"]["recall_at_1_mean"],
        ]
        x = np.arange(len(cats))
        w = 0.25
        b1 = ax.bar(x - w, mrr_vals, w, label="5-Fold CV MRR@5 (toàn |Q|=1.150)", color="#0284C7")
        b2 = ax.bar(x, r1_vals, w, label="Recall@1 (1.003 mục có đích)", color="#0D9488")
        b3 = ax.bar(x + w, pos_mrr_vals, w, label="MRR@5 mục có đích", color="#D97706")
        ax.set_xticks(x)
        ax.set_xticklabels(cats, fontsize=8.9, fontweight="bold", color="#1E293B")
        ax.set_ylim(0.72, 1.07)
        ax.set_yticks([0.75, 0.85, 0.95, 1.00])
        ax.set_ylabel("Điểm 5-Fold CV", fontsize=9.0, color="#334155")
        ax.set_title("Ablation Study trên 5-Fold Manual CV (25 bài, S3 khuyết tiêu đề — LightGBM Ranker)", fontsize=10.2, fontweight="bold", color="#0F2744", pad=15)
        ax.grid(axis="y", linestyle="--", alpha=0.35, color="#CBD5E1")
        ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=8.1, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.06))
        for grp in (b1, b2, b3):
            for b in grp:
                v = b.get_height()
                ax.text(b.get_x() + b.get_width() / 2, v + 0.008, f"{v:.4f}", ha="center", va="bottom", fontsize=7.6, fontweight="bold", color="#0F172A")
    else:
        abl_keys = ["A1_base_metadata", "A2_plus_pool_relative", "A3_full_with_m2_hierarchy"]
        abl_labels = ["A1: Metadata\n(17 đặc trưng)", "A2: + Pool\n(21 đặc trưng)", "A3: + Hierarchy M2\n(25 đặc trưng)"]
        val_mrr = [ablation[k]["metrics"]["valid"]["mrr_at_5"] for k in abl_keys]
        tst_mrr = [ablation[k]["metrics"]["test"]["mrr_at_5"] for k in abl_keys]
        tst_pos = [ablation[k]["metrics"]["test"]["mrr_at_5_positive_only"] for k in abl_keys]
        x = np.arange(len(abl_keys))
        w = 0.25
        b1 = ax.bar(x - w, val_mrr, w, label="Valid MRR@5", color="#64748B")
        b2 = ax.bar(x, tst_mrr, w, label="Test MRR@5", color="#0284C7")
        b3 = ax.bar(x + w, tst_pos, w, label="Test Positive-only", color="#D97706")
        ax.set_xticks(x)
        ax.set_xticklabels(abl_labels, fontsize=9.0, fontweight="bold", color="#1E293B")
        ax.set_ylim(0, 1.30)
        ax.set_ylabel("MRR@5", fontsize=9.0, color="#334155")
        ax.set_title("Nghiên cứu loại bỏ đặc trưng (Ablation Study — LightGBM Ranker)", fontsize=10.5, fontweight="bold", color="#0F2744", pad=16)
        ax.legend(frameon=False, fontsize=8.3, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.04))
        for grp in (b1, b2, b3):
            for b in grp:
                v = b.get_height()
                ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.4f}", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#0F172A")

    fig.tight_layout(pad=0.9)
    p4 = charts_dir / "chart_m3_ablation.png"
    fig.savefig(p4)
    plt.close(fig)
    paths["ablation"] = p4

    return paths


def _add_rect(slide, x: float, y: float, w: float, h: float, fill: RGBColor, line: RGBColor | None = None, radius: bool = False):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is not None:
        shp.line.color.rgb = line
        shp.line.width = Pt(1.2)
    else:
        shp.line.fill.background()
    if radius and len(shp.adjustments) > 0:
        shp.adjustments[0] = 0.04
    return shp


def _add_card(slide, x: float, y: float, w: float, h: float, title: str, accent: RGBColor = NAVY):
    card = _add_rect(slide, x, y, w, h, WHITE, line=BORDER, radius=True)
    hdr = _add_rect(slide, x, y, w, 0.50, accent, line=None, radius=False)
    tf = hdr.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.18)
    tf.margin_right = Inches(0.15)
    p = tf.paragraphs[0]
    p.text = title
    p.font.name = FONT_NAME
    p.font.size = Pt(14.5)
    p.font.bold = True
    p.font.color.rgb = WHITE
    return card


def _add_bullets(slide, x: float, y: float, w: float, h: float, items: list[tuple[str, str]], font_size: float = 11.2, space_after: float = 5.0):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.05)
    tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.03)
    tf.margin_bottom = Inches(0.03)
    for idx, (lead, body) in enumerate(items):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        p.line_spacing = 1.15
        r1 = p.add_run()
        r1.text = f"▪ {lead}: " if lead else "▪ "
        r1.font.name = FONT_NAME
        r1.font.size = Pt(font_size)
        r1.font.bold = True
        r1.font.color.rgb = NAVY
        r2 = p.add_run()
        r2.text = body
        r2.font.name = FONT_NAME
        r2.font.size = Pt(font_size)
        r2.font.color.rgb = TEXT_DARK
    return tb


def build_poster(
    *,
    m2_summary_path: Path,
    m3_workspace: Path,
    output_pptx: Path,
) -> dict[str, Any]:
    m2_summary = json.loads(m2_summary_path.read_text(encoding="utf-8"))
    m3_summary = json.loads((m3_workspace / "m3_results_summary.json").read_text(encoding="utf-8"))
    feat_imp = json.loads((m3_workspace / "m3_feature_importance.json").read_text(encoding="utf-8"))
    ablation = json.loads((m3_workspace / "m3_ablation.json").read_text(encoding="utf-8"))
    hf_manifest = json.loads((m3_workspace / "hf_staging_manifest.json").read_text(encoding="utf-8"))
    err_analysis = json.loads((m3_workspace / "m3_error_analysis.json").read_text(encoding="utf-8"))
    eda_path = m3_workspace / "m3_feature_eda.json"
    feature_eda = json.loads(eda_path.read_text(encoding="utf-8")) if eda_path.is_file() else None

    charts_dir = output_pptx.parent / "charts"
    charts = render_charts(m2_summary, m3_summary, feat_imp, ablation, charts_dir, feature_eda=feature_eda)

    prs = Presentation()
    prs.slide_width = Inches(A2_WIDTH_IN)
    prs.slide_height = Inches(A2_HEIGHT_IN)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank layout

    # Nền toàn trang
    _add_rect(slide, 0.0, 0.0, A2_WIDTH_IN, A2_HEIGHT_IN, SLATE_BG)

    # ===== HEADER BANNER =====
    _add_rect(slide, 0.0, 0.0, A2_WIDTH_IN, 2.48, NAVY)
    _add_rect(slide, 0.0, 2.48, A2_WIDTH_IN, 0.10, SKY)

    tb_tag = slide.shapes.add_textbox(Inches(0.45), Inches(0.18), Inches(15.64), Inches(0.32))
    p = tb_tag.text_frame.paragraphs[0]
    p.text = "ĐỒ ÁN NHẬP MÔN KHOA HỌC DỮ LIỆU • KHOA CNTT — TRƯỜNG ĐH KHOA HỌC TỰ NHIÊN, ĐHQG TP.HCM"
    p.font.name = FONT_NAME
    p.font.size = Pt(12.5)
    p.font.bold = True
    p.font.color.rgb = SKY_LIGHT

    tb_title = slide.shapes.add_textbox(Inches(0.45), Inches(0.52), Inches(15.64), Inches(1.10))
    tf_t = tb_title.text_frame
    tf_t.word_wrap = True
    p = tf_t.paragraphs[0]
    p.text = "arXiv Harvester: Thu thập đa phiên bản, Phân tích cấu trúc LaTeX phân cấp & Khớp trích dẫn BibTeX trên 25.000 bài báo"
    p.font.name = FONT_NAME
    p.font.size = Pt(25.0)
    p.font.bold = True
    p.font.color.rgb = WHITE

    tb_auth = slide.shapes.add_textbox(Inches(0.45), Inches(1.68), Inches(15.64), Inches(0.72))
    tf_a = tb_auth.text_frame
    tf_a.word_wrap = True
    p1 = tf_a.paragraphs[0]
    p1.text = "Nguyễn Quốc Đạt (24120282)  •  Nguyễn Đình Tuấn (24120237)  •  Trần Nguyên Tân (24120438)  •  Dương Phan Minh Trí (24120470)  •  Trịnh Vỹ Triết (24120474)"
    p1.font.name = FONT_NAME
    p1.font.size = Pt(12.0)
    p1.font.bold = True
    p1.font.color.rgb = WHITE
    p2 = tf_a.add_paragraph()
    p2.space_before = Pt(4)
    p2.text = "GitHub: github.com/NguyenQuocDat06-AI/arxiv-harvester   |   Jupyter Book: nguyenquocdat06-ai.github.io/arxiv-harvester-book   |   Dataset: huggingface.co/datasets/nquocdat06/arxiv-harvester-data"
    p2.font.name = FONT_NAME
    p2.font.size = Pt(10.5)
    p2.font.color.rgb = SKY_LIGHT

    # ===== 5-KPI STRIP =====
    best_model = m3_summary["best_model"]
    best_test = m3_summary["models"][best_model]["test"]
    best_manual = m3_summary["models"][best_model]["test_manual"]
    sc = m2_summary["m2_status_counts"]
    tex_verified = m2_summary["source_audit_summary"]["reasons"]["tex_verified"]
    parsed_pct = (sc["success"] + sc["partial"]) / tex_verified * 100.0
    elem_red = m2_summary["m2_deduplication"]["elements"]["reduction_rate"] * 100.0
    bib_red = m2_summary["m2_deduplication"]["bibtex"]["reduction_rate"] * 100.0
    hf_gb = hf_manifest["total_bytes"] / (1024 ** 3)

    kpis = [
        ("25.000 bài", "41.498 phiên bản (5 × 5.000 bài)", NAVY),
        (f"{parsed_pct:.2f}%", "Phiên bản TeX parse được cấu trúc", SKY),
        (f"-{elem_red:.1f}% / -{bib_red:.1f}%", "Khử trùng Elements & BibTeX", TEAL),
        (f"MRR@5 = {best_test['mrr_at_5']:.4f}", f"{MODEL_SHORT[best_model]} (R@1={best_test['recall_at_1']*100:.0f}%)", AMBER),
        ("6 bảng Parquet", f"{hf_gb:.2f} GiB chuẩn Hugging Face", NAVY),
    ]
    kpi_w = 2.951
    kpi_gap = 0.22
    for idx, (val_txt, sub_txt, accent_col) in enumerate(kpis):
        kx = 0.45 + idx * (kpi_w + kpi_gap)
        _add_rect(slide, kx, 2.76, kpi_w, 1.32, WHITE, line=BORDER, radius=True)
        _add_rect(slide, kx, 2.76, kpi_w, 0.10, accent_col, line=None, radius=False)
        tb = slide.shapes.add_textbox(Inches(kx + 0.10), Inches(2.92), Inches(kpi_w - 0.20), Inches(1.10))
        tf = tb.text_frame
        tf.word_wrap = True
        pv = tf.paragraphs[0]
        pv.alignment = PP_ALIGN.CENTER
        pv.text = val_txt
        pv.font.name = FONT_NAME
        pv.font.size = Pt(18.5 if len(val_txt) < 14 else 15.5)
        pv.font.bold = True
        pv.font.color.rgb = accent_col
        ps = tf.add_paragraph()
        ps.alignment = PP_ALIGN.CENTER
        ps.space_before = Pt(4)
        ps.text = sub_txt
        ps.font.name = FONT_NAME
        ps.font.size = Pt(10.0)
        ps.font.color.rgb = TEXT_MUTED

    # ===== CỘT TRÁI (x=0.45, w=7.64) =====
    lx, cw = 0.45, 7.64
    card_bounds: list[tuple[str, float, float, float, float]] = []

    # Card L1: Kiến trúc hệ thống (4.30 -> 8.45)
    _add_card(slide, lx, 4.30, cw, 4.15, "1. KIẾN TRÚC PIPELINE ĐẦU CUỐI (M1 → M2 → M3)", NAVY)
    card_bounds.append(("L1", lx, 4.30, lx + cw, 8.45))

    stages = [
        ("M1 • Crawling", "arXiv + S2 Batch\n≥3s pacing, resume", NAVY),
        ("M2 • Parsing", "TeX root, Hierarchy\n& Khử trùng 2 tầng", SKY),
        ("M3 • Matching", "25 đặc trưng cổ điển\nLightGBM Ranker", TEAL),
        ("HF • 6 bảng", "Parquet phân mảnh\nYAML Dataset Card", AMBER),
    ]
    sw = 1.66
    sgap = 0.20
    for i, (st_title, st_desc, st_col) in enumerate(stages):
        sx = lx + 0.18 + i * (sw + sgap)
        box = _add_rect(slide, sx, 4.95, sw, 1.08, st_col, radius=True)
        tf = box.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p1 = tf.paragraphs[0]
        p1.alignment = PP_ALIGN.CENTER
        p1.text = st_title
        p1.font.name = FONT_NAME
        p1.font.size = Pt(11.0)
        p1.font.bold = True
        p1.font.color.rgb = WHITE
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        p2.space_before = Pt(3)
        p2.text = st_desc
        p2.font.name = FONT_NAME
        p2.font.size = Pt(9.2)
        p2.font.color.rgb = WHITE

    _add_bullets(
        slide,
        lx + 0.16,
        6.16,
        cw - 0.32,
        2.15,
        [
            ("Thu thập bền vững (M1)", "Tách khóa rate-limit arXiv (≥3s/request, 1 kết nối) và S2 batch (50 bài/POST); hỗ trợ HTTP Range resume, chuỗi backup Drive kiểm chứng SHA-256 và giữ .bbl bổ trợ."),
            ("Phân tích phân cấp (M2)", "Tự dò compilation root + \\input/\\include, dựng cây (Document → Section → Sentence/Math/Figure/List), chuẩn hóa LaTeX/toán, khử trùng 2 tầng & đổi tên \\cite{} xuyên phiên bản."),
            ("Kiểm chuẩn Out-of-Core", "Xác minh 5 bảng bằng SQLite trên đĩa từng đồ thị (arxiv_id, version): structural_valid = True, 0 chu trình, 0 thiếu phiên bản trên 41.498 version."),
        ],
        font_size=10.5,
        space_after=4.5,
    )

    # Card L2: Kết quả M1-M2, Benchmark & Bằng chứng EDA Chất lượng BibTeX (8.70 -> 16.25)
    _add_card(slide, lx, 8.70, cw, 7.55, "2. THỐNG KÊ M1–M2, BENCHMARK COLAB & EDA CHẤT LƯỢNG BIBTEX", SKY)
    card_bounds.append(("L2", lx, 8.70, lx + cw, 16.25))

    bm = m2_summary["benchmark_summary"]
    _add_bullets(
        slide,
        lx + 0.16,
        9.30,
        cw - 0.32,
        1.98,
        [
            ("Độ phủ nguồn & trích dẫn", f"25.000 bài (0 trùng chéo thành viên), {m2_summary['source_audit_summary']['verified']:,}/41.498 version đã audit, {m2_summary['m1_references']:,} working refs và {m2_summary['course_references']:,} arXiv-keyed refs."),
            ("Hiệu năng Colab CPU-only", f"5 phiên độc lập không gối giờ (reused = 0): tổng {bm['total_profiler_sec']:,.1f}s (~5h11m), TB {bm['avg_sec_per_unique_publication']:.3f}s/bài, Peak RSS {bm['max_session_peak_rss_mib']:.1f} MiB (TB trọng số {bm['session_time_weighted_avg_rss_mib']:.1f} MiB)."),
            ("Chất lượng phân tích M2", f"33.025 success (85,66% TeX) + 4.503 partial (97,34% parse cấu trúc); khử trùng Elements {m2_summary['m2_deduplication']['elements']['before']/1e6:.2f}M → {m2_summary['m2_deduplication']['elements']['after']/1e6:.2f}M, BibTeX {m2_summary['m2_deduplication']['bibtex']['before']/1e6:.2f}M → {m2_summary['m2_deduplication']['bibtex']['after']/1e6:.2f}M."),
        ],
        font_size=10.3,
        space_after=3.8,
    )
    slide.shapes.add_picture(str(charts["m1_m2"]), Inches(lx + 0.14), Inches(11.34), width=Inches(cw - 0.28))

    # Hộp tóm tắt EDA chất lượng BibTeX & độ trễ năm (lấp gọn vùng trống dưới Chart 1: 14.38 -> 16.08)
    _add_rect(slide, lx + 0.16, 14.38, cw - 0.32, 1.68, CARD_TINT, line=SKY, radius=True)
    if feature_eda and "metadata_and_year_lag_eda" in feature_eda:
        meda = feature_eda["metadata_and_year_lag_eda"]
        yl = meda["year_lag_distribution"]
        eda_bullets = [
            ("Bằng chứng EDA định hướng đặc trưng M3 (n = 29.309 mục BibTeX / 1,12M cặp)", f"70,8% thiếu DOI, 89,0% thiếu URL, chỉ {meda['has_explicit_arxiv_id_pct']:.1f}% có sẵn arXiv ID và {meda['author_count_mismatch_pct']:.1f}% cặp dương lệch số lượng tác giả (TB lệch {meda['mean_author_count_diff']:.1f} do 'et al.') → cần khớp mờ tiêu đề + recall họ tác giả."),
            ("Bất đối xứng độ trễ năm & độ phủ cây M2", f"Độ trễ năm (bib_year − ref_year, n={meda['year_lag_samples']:,}): 0 năm = {yl['0']['pct']:.1f}%, +1 năm = {yl['1']['pct']:.1f}% (preprint → hội nghị) so với −1 năm chỉ {yl['-1']['pct']:.1f}% → chứng minh cần year_diff_signed; {meda['has_m2_hierarchy_ctx_pct']:.1f}% mục BibTeX giải được ngữ cảnh \\cite{{}} trong cây M2."),
        ]
    else:
        eda_bullets = [
            ("Phân bổ dữ liệu 5 thành viên", "Mỗi thành viên phụ trách đúng 5.000 bài báo (0 trùng chéo), đảm bảo mỗi lát dữ liệu cá nhân đều đạt chuẩn M1–M2–M3 (5 bài Manual ≥20 mục + 12% Auto)."),
        ]
    _add_bullets(slide, lx + 0.24, 14.44, cw - 0.48, 1.56, eda_bullets, font_size=9.7, space_after=3.5)

    # Card L3: Bộ dữ liệu 6 bảng Hugging Face (16.50 -> 22.65)
    _add_card(slide, lx, 16.50, cw, 6.15, "3. BỘ DỮ LIỆU 6 BẢNG PARQUET CHUẨN HUGGING FACE", NAVY)
    card_bounds.append(("L3", lx, 16.50, lx + cw, 22.65))

    tbl_shape = slide.shapes.add_table(7, 4, Inches(lx + 0.18), Inches(17.16), Inches(cw - 0.36), Inches(3.85))
    tbl = tbl_shape.table
    tbl.columns[0].width = Inches(1.45)
    tbl.columns[1].width = Inches(1.30)
    tbl.columns[2].width = Inches(0.85)
    tbl.columns[3].width = Inches(3.68)

    headers = ["Bảng", "Số dòng", "Shards", "Cột chính (Schema phẳng, Snappy Parquet)"]
    tbl_meta = [
        ("papers", "arxiv_id, title, authors[], submission_date, revised_dates[], venue"),
        ("references", "arxiv_id, ref_arxiv_id, ref_title, ref_authors[], ref_submission_date, ref_s2_id"),
        ("elements", "element_id, arxiv_id, kind (dict), content"),
        ("hierarchy", "arxiv_id, version, element_id, parent_id"),
        ("bibtex", "arxiv_id, citation_key, entry_type (dict), title, authors[], year, doi, journal, url"),
        ("predictions", "arxiv_id, partition (dict), citation_key, groundtruth_arxiv_id, cand_1..cand_5"),
    ]
    for c_idx, h_txt in enumerate(headers):
        cell = tbl.cell(0, c_idx)
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = cell.text_frame.paragraphs[0]
        p.text = h_txt
        p.font.name = FONT_NAME
        p.font.size = Pt(10.0)
        p.font.bold = True
        p.font.color.rgb = WHITE

    for r_idx, (tname, schema_desc) in enumerate(tbl_meta, start=1):
        tinfo = hf_manifest["tables"][tname]
        row_vals = [tname, f"{tinfo['rows']:,}", str(tinfo["shards"]), schema_desc]
        bg = WHITE if r_idx % 2 == 1 else SLATE_BG
        for c_idx, val in enumerate(row_vals):
            cell = tbl.cell(r_idx, c_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            p.text = val
            p.font.name = FONT_NAME
            p.font.size = Pt(9.2 if c_idx == 3 else 9.8)
            p.font.bold = (c_idx == 0)
            p.font.color.rgb = NAVY if c_idx == 0 else TEXT_DARK

    _add_bullets(
        slide,
        lx + 0.16,
        21.14,
        cw - 0.32,
        1.38,
        [
            ("Chuẩn streaming Hugging Face", "Bố cục data/<table>/*.parquet + YAML Dataset Card (README.md), không dùng custom script, không chứa JSON lồng nhau; xác minh live preview/viewer/search/filter/statistics = True."),
            ("Hỗ trợ cả nhóm & từng thành viên", f"Tổng {hf_gb:.2f} GiB (25.000 bài) và cấu trúc chuẩn hóa 5 × 5.000 bài cá nhân, mỗi lát đạt đủ 6 bảng & chuẩn gán nhãn M3 độc lập."),
        ],
        font_size=10.1,
        space_after=3.8,
    )

    # ===== CỘT PHẢI (x=8.44, w=7.64) =====
    rx = 8.44

    # Card R1: Gán nhãn M3 & 25 đặc trưng (4.30 -> 10.65)
    _add_card(slide, rx, 4.30, cw, 6.35, "4. MILESTONE 3: GÁN NHÃN & 25 ĐẶC TRƯNG CỔ ĐIỂN (KÈM HIERARCHY M2)", TEAL)
    card_bounds.append(("R1", rx, 4.30, rx + cw, 10.65))

    lbl = m3_summary["labeling"]
    _add_bullets(
        slide,
        rx + 0.16,
        4.92,
        cw - 0.32,
        2.38,
        [
            ("Gán nhãn chuẩn theo thành viên (k = 5)", f"Manual pool: {lbl['manual_papers']} bài (5 bài/thành viên, min Q = 26 ≥ 20, tổng {lbl['manual_entries']:,} mục). Auto pool: {lbl['auto_papers']:,} bài ({lbl['auto_fraction_of_remaining']*100:.1f}% > ngưỡng 10%, tổng {lbl['auto_entries']:,} mục)."),
            ("Chia tập chống rò rỉ theo arxiv_id", f"Test: 5 Manual + 5 Auto ({lbl['split_entries']['test']:,} mục) • Valid: 5 Manual + 5 Auto ({lbl['split_entries']['valid']:,} mục) • Train: {lbl['split_papers']['train']['manual']} Manual + {lbl['split_papers']['train']['auto']:,} Auto ({lbl['split_entries']['train']:,} mục). TF-IDF chỉ fit trên Train."),
            ("25 đặc trưng (100% cổ điển, 0 LLM)", "7 tiêu đề + 5 tác giả + 5 thời gian/ID + 4 tương đối trong pool + 4 ngữ cảnh cây Hierarchy M2. Trên 1,12M cặp thật, [M2] khớp họ tác giả trong câu \\cite{} đạt AUC = 0,7825 (63,9% dương vs 7,4% âm — gấp 8,6×)."),
        ],
        font_size=10.1,
        space_after=3.8,
    )
    slide.shapes.add_picture(str(charts["features"]), Inches(rx + 0.14), Inches(7.36), width=Inches(cw - 0.28))

    # Card R2: So sánh mô hình & Ablation Study (10.90 -> 18.25)
    _add_card(slide, rx, 10.90, cw, 7.35, "5. SO SÁNH MÔ HÌNH, ĐÁNH GIÁ MRR@5 & STRESS-TEST ABLATION", AMBER)
    card_bounds.append(("R2", rx, 10.90, rx + cw, 18.25))

    slide.shapes.add_picture(str(charts["models"]), Inches(rx + 0.14), Inches(11.48), width=Inches(cw - 0.28))
    slide.shapes.add_picture(str(charts["ablation"]), Inches(rx + 0.14), Inches(14.58), width=Inches(cw - 0.28))

    tb_m3note = slide.shapes.add_textbox(Inches(rx + 0.18), Inches(17.08), Inches(cw - 0.36), Inches(1.06))
    tf_n = tb_m3note.text_frame
    tf_n.word_wrap = True
    pn = tf_n.paragraphs[0]
    pn.line_spacing = 1.15
    r1 = pn.add_run()
    r1.text = "Kết quả thực nghiệm cốt lõi: "
    r1.font.name = FONT_NAME
    r1.font.size = Pt(10.2)
    r1.font.bold = True
    r1.font.color.rgb = NAVY
    r2 = pn.add_run()
    best_auto = m3_summary["models"][best_model]["test_auto"]
    if feature_eda and "manual_5fold_cv" in feature_eda:
        s3_t_lgb = feature_eda["stress_test"]["S3_missing_title_rescue"]["models"]["lightgbm_ranker"]["test"]["mrr_at_5"]
        s3_t_heu = feature_eda["stress_test"]["S3_missing_title_rescue"]["models"]["heuristic_baseline"]["test"]["mrr_at_5"]
        cv_s3 = feature_eda["manual_5fold_cv"]["S3_missing_title_rescue"]
        r2.text = (
            f"Trên Test chuẩn (|Q|=540), {MODEL_SHORT[best_model]} đạt đúng trần lý thuyết MRR@5 = {best_test['mrr_at_5']:.4f} "
            f"(100% Recall@1 trên 373 mục có đích; Test-Manual = {best_manual['mrr_at_5']:.4f}, Test-Auto = {best_auto['mrr_at_5']:.4f}). "
            f"Khi khuyết tiêu đề .bbl (S3), LightGBM vượt Heuristic tới +{s3_t_lgb - s3_t_heu:.4f} MRR@5 trên Test và "
            f"A3 (+Hierarchy M2) đạt đỉnh 5-Fold Manual CV ({cv_s3['ablation']['A3_full_with_m2_hierarchy']['mrr_at_5_mean']:.4f}, R@1 = {cv_s3['ablation']['A3_full_with_m2_hierarchy']['recall_at_1_mean']*100:.1f}% vs Heuristic {cv_s3['models']['heuristic_baseline']['recall_at_1_mean']*100:.1f}%)."
        )
    else:
        r2.text = (
            f"{MODEL_SHORT[best_model]} đạt MRR@5 = {best_test['mrr_at_5']:.4f} trên toàn tập |Q|={best_test['n_entries']} "
            f"(Recall@1 = {best_test['recall_at_1']*100:.1f}%, Test-Manual = {best_manual['mrr_at_5']:.4f}, Test-Auto = {best_auto['mrr_at_5']:.4f})."
        )
    r2.font.name = FONT_NAME
    r2.font.size = Pt(9.9)
    r2.font.color.rgb = TEXT_DARK

    # Card R3: Phân tích lỗi & Kết luận (18.50 -> 22.65)
    _add_card(slide, rx, 18.50, cw, 4.15, "6. PHÂN TÍCH LỖI & ĐÓNG GÓP CỐT LÕI", NAVY)
    card_bounds.append(("R3", rx, 18.50, rx + cw, 22.65))

    n_neg_test = best_test["n_entries"] - best_test["n_positive_entries"]
    neg_pct = (n_neg_test / best_test["n_entries"] * 100.0) if best_test["n_entries"] else 0.0
    _add_bullets(
        slide,
        rx + 0.16,
        19.12,
        cw - 0.32,
        3.40,
        [
            ("Trần lý thuyết từ hàng all-negative", f"Trong tập Test có {n_neg_test}/{best_test['n_entries']} mục ({neg_pct:.1f}%) là tài liệu không có bản arXiv (sách, hội nghị/tạp chí đóng), tạo hàng âm toàn phần — xác định trần tự nhiên MRR@5 = 373/540 = {best_test['mrr_at_5']:.4f}."),
            ("Học máy cổ điển vượt trội khi .bbl nhiễu", "Trên 5-Fold Manual CV (25 bài / 1.150 mục), ngay cả ở dữ liệu sạch ML đạt 100% R@1 (Heuristic 99,9%); khi rút gọn hoặc khuyết tiêu đề (S2/S3), LightGBM Ranker giữ 96,1%–99,3% R@1 (Heuristic tụt còn 81,4%–91,7%)."),
            ("Vai trò phục hồi của Pool & Hierarchy M2", "Trên S0, 2 đặc trưng Pool-relative đóng góp >98% LightGBM Gain; khi mất tiêu đề (S3), ngữ cảnh câu \\cite{} (hier_context_title_tfidf_cosine) vươn lên Top-7 Gain toàn cục và nâng A3 lên đỉnh 5-Fold CV (0,8530)."),
            ("Tái lập 100% & Tuân thủ quy định", "100% học máy cổ điển (không dùng LLM/pretrained), mã nguồn sạch có CI tự động, notebook EDA M3, báo cáo Jupyter Book M1–M2 và bộ 6 bảng Parquet trên Hugging Face."),
        ],
        font_size=10.0,
        space_after=4.2,
    )

    # ===== FOOTER =====
    _add_rect(slide, 0.0, 22.86, A2_WIDTH_IN, 0.525, NAVY)
    tb_f = slide.shapes.add_textbox(Inches(0.45), Inches(22.95), Inches(15.64), Inches(0.35))
    pf = tb_f.text_frame.paragraphs[0]
    pf.alignment = PP_ALIGN.CENTER
    pf.text = "arXiv Harvester • Nhập môn Khoa học dữ liệu (Chương trình Chuẩn) • Khổ đứng A2 (420 × 594 mm) • Nguồn: arXiv API, Semantic Scholar API, LightGBM, scikit-learn"
    pf.font.name = FONT_NAME
    pf.font.size = Pt(10.2)
    pf.font.color.rgb = SKY_LIGHT

    output_pptx.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_pptx))

    # Kiểm tra hình học tự động: 1 slide, đúng A2 portrait, không tràn biên, không đè card
    check_prs = Presentation(str(output_pptx))
    assert len(check_prs.slides) == 1, f"Expected 1 slide, got {len(check_prs.slides)}"
    w_mm = (check_prs.slide_width / 914400.0) * 25.4
    h_mm = (check_prs.slide_height / 914400.0) * 25.4
    assert abs(w_mm - 420.0) < 0.5 and abs(h_mm - 594.0) < 0.5, f"Wrong A2 size: {w_mm:.2f}x{h_mm:.2f}mm"

    overlaps = []
    for i in range(len(card_bounds)):
        n1, x1a, y1a, x1b, y1b = card_bounds[i]
        assert x1a >= 0 and y1a >= 0 and x1b <= A2_WIDTH_IN + 0.01 and y1b <= A2_HEIGHT_IN + 0.01
        for j in range(i + 1, len(card_bounds)):
            n2, x2a, y2a, x2b, y2b = card_bounds[j]
            if x1a < x2b and x2a < x1b and y1a < y2b and y2a < y1b:
                overlaps.append((n1, n2))
    assert not overlaps, f"Card overlaps detected: {overlaps}"

    return {
        "pptx_path": str(output_pptx),
        "slides": len(check_prs.slides),
        "width_mm": round(w_mm, 2),
        "height_mm": round(h_mm, 2),
        "charts": {k: str(v) for k, v in charts.items()},
        "size_bytes": output_pptx.stat().st_size,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate Portrait A2 Vietnamese academic poster (.pptx).")
    parser.add_argument(
        "--m2-summary",
        default="build/m2_workspace/team_25000/consolidation_summary.json",
        help="Path to M1-M2 consolidation_summary.json",
    )
    parser.add_argument(
        "--m3-workspace",
        default="build/m3_workspace",
        help="Directory containing M3 JSON reports and hf_staging_manifest.json",
    )
    parser.add_argument(
        "--output",
        default="build/poster/arXiv_Harvester_Poster_A2.pptx",
        help="Output .pptx file path",
    )
    args = parser.parse_args(argv)

    info = build_poster(
        m2_summary_path=Path(args.m2_summary),
        m3_workspace=Path(args.m3_workspace),
        output_pptx=Path(args.output),
    )
    print(json.dumps(info, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
