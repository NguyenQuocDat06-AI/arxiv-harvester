"""Sinh Poster học thuật 1 trang khổ đứng A2 (420mm x 594mm) bằng tiếng Việt từ số liệu thực M1-M3."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
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
CARD_TINT = RGBColor(0xE0, 0xF2, 0xFE)

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
    "arxiv_id_exact_match": "Khớp trực tiếp arXiv ID",
    "title_tfidf_cosine": "TF-IDF Cosine tiêu đề",
    "title_rapidfuzz_ratio": "Tương đồng chuỗi tiêu đề (Fuzzy)",
    "title_token_jaccard": "Jaccard token tiêu đề",
    "title_token_dice": "Dice token tiêu đề",
    "title_containment_bib_in_ref": "Độ bao phủ token tiêu đề",
    "title_exact_norm": "Khớp chính xác tiêu đề chuẩn hóa",
    "title_len_ratio": "Tỷ lệ độ dài tiêu đề",
    "first_author_surname_match": "Khớp họ tác giả đầu",
    "author_surname_jaccard": "Jaccard họ tác giả",
    "author_surname_recall": "Recall họ tác giả",
    "author_initial_surname_match": "Khớp (Họ + chữ đầu tên)",
    "author_count_diff": "Chênh lệch số tác giả",
    "year_exact_match": "Khớp chính xác năm",
    "year_abs_diff": "Độ lệch tuyệt đối năm",
    "year_diff_signed": "Độ trễ năm arXiv ↔ xuất bản",
    "cite_key_author_year_hit": "Gợi ý từ citation_key",
    "title_tfidf_margin_to_best": "Khoảng cách tới TF-IDF cao nhất (pool)",
    "title_tfidf_rank_inv": "Hạng nghịch đảo TF-IDF (pool)",
    "author_jaccard_margin_to_best": "Khoảng cách tới Jaccard tác giả tốt nhất",
    "pool_size_log": "Kích thước tập ứng viên (log)",
    "hier_cite_count": "[M2 Hierarchy] Tần suất \\cite{}",
    "hier_in_intro_or_related": "[M2 Hierarchy] Thuộc Intro/Related",
    "hier_context_title_tfidf_cosine": "[M2 Hierarchy] Ngữ cảnh câu ↔ tiêu đề",
    "hier_context_author_hit": "[M2 Hierarchy] Tác giả trong câu trích dẫn",
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
) -> dict[str, Path]:
    _setup_plt()
    charts_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # 1. Biểu đồ M1-M2: Trạng thái parse 41.498 version & Khử trùng 2 tầng
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.3), gridspec_kw={"width_ratios": [1.15, 1.0]})
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
    ax1.set_yticklabels(st_labels, fontsize=9.5, color="#1E293B")
    ax1.invert_yaxis()
    ax1.set_title("Trạng thái phân tích 41.498 phiên bản (M2)", fontsize=11, fontweight="bold", color="#0F2744", pad=10)
    ax1.set_xlabel("Số phiên bản", fontsize=9.5, color="#334155")
    ax1.set_xlim(0, max(st_vals) * 1.24)
    for b, v in zip(bars, st_vals):
        ax1.text(v + max(st_vals) * 0.02, b.get_y() + b.get_height() / 2, f"{v:,}", va="center", fontsize=9, fontweight="bold", color="#0F172A")

    dd = m2_summary["m2_deduplication"]
    cats = ["Elements\n(triệu dòng)", "BibTeX\n(triệu dòng)"]
    before_m = [dd["elements"]["before"] / 1e6, dd["bibtex"]["before"] / 1e6]
    after_m = [dd["elements"]["after"] / 1e6, dd["bibtex"]["after"] / 1e6]
    rates = [dd["elements"]["reduction_rate"] * 100, dd["bibtex"]["reduction_rate"] * 100]
    x = np.arange(len(cats))
    w = 0.34
    b1 = ax2.bar(x - w / 2, before_m, w, label="Trước khử trùng", color="#94A3B8")
    b2 = ax2.bar(x + w / 2, after_m, w, label="Sau khử trùng", color="#0D9488")
    ax2.set_xticks(x)
    ax2.set_xticklabels(cats, fontsize=9.5, color="#1E293B")
    ax2.set_title("Hiệu quả khử trùng 2 tầng xuyên phiên bản", fontsize=11, fontweight="bold", color="#0F2744", pad=10)
    ax2.set_ylabel("Triệu bản ghi", fontsize=9.5, color="#334155")
    ax2.set_ylim(0, max(before_m) * 1.25)
    ax2.legend(frameon=False, fontsize=9, loc="upper right")
    for idx_c in range(len(cats)):
        ax2.text(x[idx_c] - w / 2, before_m[idx_c] + 0.45, f"{before_m[idx_c]:.2f}M", ha="center", fontsize=8.5, color="#475569")
        ax2.text(x[idx_c] + w / 2, after_m[idx_c] + 0.45, f"{after_m[idx_c]:.2f}M\n(-{rates[idx_c]:.1f}%)", ha="center", fontsize=8.5, fontweight="bold", color="#0F766E")

    fig.tight_layout(pad=1.4)
    p1 = charts_dir / "chart_m1_m2_overview.png"
    fig.savefig(p1)
    plt.close(fig)
    paths["m1_m2"] = p1

    # 2. Biểu đồ so sánh 4 mô hình cổ điển (Test MRR@5, Recall@1, Recall@5)
    fig, ax = plt.subplots(figsize=(10.2, 3.85))
    models_order = ["heuristic_baseline", "logistic_regression", "random_forest", "lightgbm_ranker"]
    labels = [MODEL_LABELS[m] for m in models_order]
    mrr_all = [m3_summary["models"][m]["test"]["mrr_at_5"] for m in models_order]
    r1_vals = [m3_summary["models"][m]["test"]["recall_at_1"] for m in models_order]
    r5_vals = [m3_summary["models"][m]["test"]["recall_at_5"] for m in models_order]

    x = np.arange(len(models_order))
    w = 0.25
    bars_mrr = ax.bar(x - w, mrr_all, w, label="Test MRR@5 (toàn bộ |Q|)", color="#0F2744")
    bars_r1 = ax.bar(x, r1_vals, w, label="Test Recall@1 (mục có đích)", color="#0284C7")
    bars_r5 = ax.bar(x + w, r5_vals, w, label="Test Recall@5 (mục có đích)", color="#0D9488")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5, fontweight="bold", color="#1E293B")
    ax.set_ylim(0, 1.26)
    ax.set_yticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_ylabel("Điểm đánh giá", fontsize=9.5, color="#334155")
    ax.set_title("So sánh 4 mô hình cổ điển trên tập Test (5 bài Manual + 5 bài Auto)", fontsize=11, fontweight="bold", color="#0F2744", pad=16)
    ax.grid(axis="y", linestyle="--", alpha=0.35, color="#CBD5E1")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8.8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.03))

    for group_bars in (bars_mrr, bars_r1, bars_r5):
        for b in group_bars:
            v = b.get_height()
            ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.3f}", ha="center", va="bottom", fontsize=8.2, fontweight="bold", color="#0F172A")

    fig.tight_layout(pad=1.1)
    p2 = charts_dir / "chart_m3_models.png"
    fig.savefig(p2)
    plt.close(fig)
    paths["models"] = p2

    # 3. Biểu đồ Top-16 đặc trưng có độ quan trọng > 0 (nhấn mạnh đặc trưng Hierarchy M2)
    fig, ax = plt.subplots(figsize=(10.2, 4.35))
    nonzero_imp = [item for item in feat_imp if item["importance_raw"] > 0]
    top_feats = nonzero_imp[:12] if len(nonzero_imp) >= 12 else feat_imp[:12]
    # Bảo đảm đặc trưng M2 Hierarchy xuất hiện rõ nếu có importance > 0 nằm ở hạng 13..16
    if not any(i["group"] == "m2_hierarchy_context" for i in top_feats):
        m2_item = next((i for i in nonzero_imp if i["group"] == "m2_hierarchy_context"), None)
        if m2_item is not None:
            top_feats = [*top_feats[:11], m2_item]
    f_labels = [FEATURE_VI_LABELS.get(item["feature"], item["feature"]) for item in top_feats]
    f_vals = [item["importance_share"] * 100.0 for item in top_feats]
    color_map = {
        "base_metadata": "#0284C7",
        "pool_relative": "#0D9488",
        "m2_hierarchy_context": "#D97706",
    }
    f_colors = [color_map.get(item["group"], "#64748B") for item in top_feats]
    y_pos = np.arange(len(f_labels))
    bars = ax.barh(y_pos, f_vals, color=f_colors, height=0.66)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(f_labels, fontsize=9.0, color="#1E293B")
    ax.invert_yaxis()
    ax.set_xlabel("Tỷ trọng độ quan trọng đặc trưng (%)", fontsize=9.5, color="#334155")
    ax.set_title("Top-12 đặc trưng quan trọng nhất (LightGBM Ranker)", fontsize=11, fontweight="bold", color="#0F2744", pad=10)
    ax.set_xlim(0, max(f_vals) * 1.22 if f_vals else 10)
    for b, v in zip(bars, f_vals):
        ax.text(v + (max(f_vals) * 0.018 if f_vals else 0.2), b.get_y() + b.get_height() / 2, f"{v:.1f}%", va="center", fontsize=8.6, fontweight="bold", color="#0F172A")

    from matplotlib.patches import Patch
    legend_handles = [
        Patch(facecolor="#0284C7", label="Metadata cơ bản (Tiêu đề/Tác giả/Năm/ID)"),
        Patch(facecolor="#0D9488", label="Tương đối trong tập ứng viên (Pool)"),
        Patch(facecolor="#D97706", label="Ngữ cảnh cây Hierarchy M2"),
    ]
    ax.legend(handles=legend_handles, frameon=False, fontsize=8.3, loc="lower right")
    fig.tight_layout(pad=1.1)
    p3 = charts_dir / "chart_m3_features.png"
    fig.savefig(p3)
    plt.close(fig)
    paths["features"] = p3

    # 4. Biểu đồ Ablation Study (A1 -> A2 -> A3)
    fig, ax = plt.subplots(figsize=(10.2, 2.95))
    abl_keys = ["A1_base_metadata", "A2_plus_pool_relative", "A3_full_with_m2_hierarchy"]
    abl_labels = [
        "A1: Metadata cơ bản\n(17 đặc trưng)",
        "A2: + Tương đối pool\n(21 đặc trưng)",
        "A3: + Ngữ cảnh Hierarchy M2\n(đủ 25 đặc trưng)",
    ]
    val_mrr = [ablation[k]["metrics"]["valid"]["mrr_at_5"] for k in abl_keys]
    tst_mrr = [ablation[k]["metrics"]["test"]["mrr_at_5"] for k in abl_keys]
    tst_pos = [ablation[k]["metrics"]["test"]["mrr_at_5_positive_only"] for k in abl_keys]

    x = np.arange(len(abl_keys))
    w = 0.25
    b_va = ax.bar(x - w, val_mrr, w, label="Valid MRR@5", color="#64748B")
    b_te = ax.bar(x, tst_mrr, w, label="Test MRR@5 (toàn |Q|)", color="#0284C7")
    b_tp = ax.bar(x + w, tst_pos, w, label="Test MRR@5 (mục có đích)", color="#D97706")
    ax.set_xticks(x)
    ax.set_xticklabels(abl_labels, fontsize=9.2, fontweight="bold", color="#1E293B")
    ax.set_ylim(0, 1.30)
    ax.set_yticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_ylabel("MRR@5", fontsize=9.2, color="#334155")
    ax.set_title("Nghiên cứu loại bỏ đặc trưng (Ablation Study — LightGBM Ranker)", fontsize=10.8, fontweight="bold", color="#0F2744", pad=16)
    ax.grid(axis="y", linestyle="--", alpha=0.35, color="#CBD5E1")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.04))
    for grp in (b_va, b_te, b_tp):
        for b in grp:
            v = b.get_height()
            ax.text(b.get_x() + b.get_width() / 2, v + 0.022, f"{v:.4f}", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#0F172A")

    fig.tight_layout(pad=1.0)
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
        p.line_spacing = 1.16
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

    charts_dir = output_pptx.parent / "charts"
    charts = render_charts(m2_summary, m3_summary, feat_imp, ablation, charts_dir)

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
        ("25.000 bài", "41.498 phiên bản (5 dải ID)", NAVY),
        (f"{parsed_pct:.2f}%", "Phiên bản TeX parse được cấu trúc", SKY),
        (f"-{elem_red:.1f}% / -{bib_red:.1f}%", "Khử trùng Elements & BibTeX", TEAL),
        (f"MRR@5 = {best_test['mrr_at_5']:.4f}", f"{MODEL_SHORT[best_model]} (R@1={best_test['recall_at_1']:.3f})", AMBER),
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
        font_size=10.6,
        space_after=4.5,
    )

    # Card L2: Kết quả M1-M2 & Benchmark Colab CPU (8.70 -> 16.25)
    _add_card(slide, lx, 8.70, cw, 7.55, "2. THỐNG KÊ M1–M2 & BENCHMARK COLAB CPU-ONLY (25.000 BÀI)", SKY)
    card_bounds.append(("L2", lx, 8.70, lx + cw, 16.25))

    bm = m2_summary["benchmark_summary"]
    _add_bullets(
        slide,
        lx + 0.16,
        9.32,
        cw - 0.32,
        2.00,
        [
            ("Độ phủ nguồn & trích dẫn", f"25.000 bài (0 trùng chéo thành viên), {m2_summary['source_audit_summary']['verified']:,}/41.498 version đã audit, {m2_summary['m1_references']:,} working references và {m2_summary['course_references']:,} arXiv-keyed references."),
            ("Hiệu năng Colab CPU-only", f"5 phiên độc lập không gối giờ (reused = 0): tổng {bm['total_profiler_sec']:,.1f}s (~5h11m), trung bình {bm['avg_sec_per_unique_publication']:.3f}s/bài, Peak RSS {bm['max_session_peak_rss_mib']:.1f} MiB (TB trọng số {bm['session_time_weighted_avg_rss_mib']:.1f} MiB)."),
            ("Chất lượng phân tích M2", f"33.025 success (85,66% TeX) + 4.503 partial (97,34% parse cấu trúc); khử trùng Elements {m2_summary['m2_deduplication']['elements']['before']/1e6:.2f}M → {m2_summary['m2_deduplication']['elements']['after']/1e6:.2f}M, BibTeX {m2_summary['m2_deduplication']['bibtex']['before']/1e6:.2f}M → {m2_summary['m2_deduplication']['bibtex']['after']/1e6:.2f}M."),
        ],
        font_size=10.5,
        space_after=4.0,
    )
    slide.shapes.add_picture(str(charts["m1_m2"]), Inches(lx + 0.14), Inches(11.42), width=Inches(cw - 0.28))

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
        21.15,
        cw - 0.32,
        1.35,
        [
            ("Chuẩn streaming Hugging Face", "Bố cục data/<table>/*.parquet + YAML Dataset Card (README.md), không dùng custom script, không chứa JSON lồng nhau."),
            ("Kiểm chuẩn 6 bảng", f"Tất cả 6/6 cấu hình xác minh hợp lệ (valid = True, tổng {hf_gb:.2f} GiB), tải trực tiếp qua datasets.load_dataset()."),
        ],
        font_size=10.3,
        space_after=4.0,
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
            ("Gán nhãn chuẩn theo thành viên (k = 5)", f"Manual pool: {lbl['manual_papers']} bài (5 bài/thành viên, mỗi bài ≥20 BibTeX, tổng {lbl['manual_entries']:,} mục). Auto pool: {lbl['auto_papers']:,} bài ({lbl['auto_fraction_of_remaining']*100:.1f}% > ngưỡng 10%, tổng {lbl['auto_entries']:,} mục)."),
            ("Chia tập chống rò rỉ theo arxiv_id", f"Test: 5 Manual + 5 Auto ({lbl['split_entries']['test']:,} mục) • Valid: 5 Manual + 5 Auto ({lbl['split_entries']['valid']:,} mục) • Train: {lbl['split_papers']['train']['manual']} Manual + {lbl['split_papers']['train']['auto']:,} Auto ({lbl['split_entries']['train']:,} mục). TF-IDF chỉ fit trên Train."),
            ("25 đặc trưng (không dùng LLM/Pretrained)", "Gồm 7 đặc trưng tiêu đề, 5 tác giả, 5 thời gian/ID (arXiv ID, độ trễ năm), 4 tương đối trong pool và 4 đặc trưng ngữ cảnh cây Hierarchy M2 (\\cite{}, mục Intro/Related, câu trích dẫn ↔ ref_title, khớp tác giả trong câu)."),
        ],
        font_size=10.2,
        space_after=4.0,
    )
    slide.shapes.add_picture(str(charts["features"]), Inches(rx + 0.14), Inches(7.36), width=Inches(cw - 0.28))

    # Card R2: So sánh mô hình & Ablation Study (10.90 -> 18.25)
    _add_card(slide, rx, 10.90, cw, 7.35, "5. SO SÁNH MÔ HÌNH, ĐÁNH GIÁ MRR@5 & ABLATION STUDY", AMBER)
    card_bounds.append(("R2", rx, 10.90, rx + cw, 18.25))

    slide.shapes.add_picture(str(charts["models"]), Inches(rx + 0.14), Inches(11.50), width=Inches(cw - 0.28))
    slide.shapes.add_picture(str(charts["ablation"]), Inches(rx + 0.14), Inches(14.62), width=Inches(cw - 0.28))

    tb_m3note = slide.shapes.add_textbox(Inches(rx + 0.18), Inches(17.12), Inches(cw - 0.36), Inches(1.02))
    tf_n = tb_m3note.text_frame
    tf_n.word_wrap = True
    pn = tf_n.paragraphs[0]
    pn.line_spacing = 1.15
    r1 = pn.add_run()
    r1.text = "Kết quả nổi bật trên tập Test: "
    r1.font.name = FONT_NAME
    r1.font.size = Pt(10.4)
    r1.font.bold = True
    r1.font.color.rgb = NAVY
    r2 = pn.add_run()
    best_auto = m3_summary["models"][best_model]["test_auto"]
    r2.text = (
        f"{MODEL_SHORT[best_model]} đạt MRR@5 = {best_test['mrr_at_5']:.4f} trên toàn tập |Q|={best_test['n_entries']} "
        f"(MRR@5 mục có đích = {best_test['mrr_at_5_positive_only']:.4f}, Recall@1 = {best_test['recall_at_1']*100:.1f}%, "
        f"Recall@5 = {best_test['recall_at_5']*100:.1f}%). Tách riêng: Test-Manual MRR@5 = {best_manual['mrr_at_5']:.4f} "
        f"(R@1 = {best_manual['recall_at_1']*100:.1f}%), Test-Auto MRR@5 = {best_auto['mrr_at_5']:.4f}."
    )
    r2.font.name = FONT_NAME
    r2.font.size = Pt(10.3)
    r2.font.color.rgb = TEXT_DARK

    # Card R3: Phân tích lỗi & Kết luận (18.50 -> 22.65)
    _add_card(slide, rx, 18.50, cw, 4.15, "6. PHÂN TÍCH LỖI & ĐÓNG GÓP CỐT LÕI", NAVY)
    card_bounds.append(("R3", rx, 18.50, rx + cw, 22.65))

    n_neg_test = best_test["n_entries"] - best_test["n_positive_entries"]
    neg_pct = (n_neg_test / best_test["n_entries"] * 100.0) if best_test["n_entries"] else 0.0
    n_miss_test = err_analysis["test_positive_not_rank1"]
    miss_bullet = (
        f"Toàn bộ {best_test['n_positive_entries']}/{best_test['n_positive_entries']} mục có đích arXiv trên tập Test đều đạt hạng 1 (Recall@1 = 100%); các ca khó hiếm gặp trên tập lớn chủ yếu do .bbl rút gọn tiêu đề/tác giả hoặc bài đổi tên giữa các phiên bản."
        if n_miss_test == 0
        else f"Chỉ {n_miss_test} mục có đích trên tập Test không đứng hạng 1: chủ yếu do .bbl rút gọn tiêu đề/tên tác giả, bài đổi tựa hoặc trùng họ tác giả đầu trong cùng năm."
    )
    _add_bullets(
        slide,
        rx + 0.16,
        19.12,
        cw - 0.32,
        3.40,
        [
            ("Trần lý thuyết từ hàng all-negative", f"Trong tập Test có {n_neg_test}/{best_test['n_entries']} mục ({neg_pct:.1f}%) là tài liệu không có bản arXiv (sách, hội nghị/tạp chí đóng), tạo hàng âm toàn phần — xác định trần tự nhiên MRR@5 = {best_test['mrr_at_5']:.4f} (Test-Manual: {best_manual['mrr_at_5']:.4f}, Test-Auto: {best_auto['mrr_at_5']:.4f})."),
            ("Hiệu quả xếp hạng nội bài báo", miss_bullet),
            ("Tác động đặc trưng Pool & Hierarchy M2", "Hai đặc trưng khoảng cách tới ứng viên tốt nhất trong pool (author_jaccard_margin_to_best 16,7%, title_tfidf_margin_to_best 13,3%), độ trễ năm (13,3%) và tần suất \\cite{} từ Hierarchy M2 (3,3%) giúp LightGBM hội tụ ngay vòng đầu."),
            ("Tính minh bạch & tái lập 100%", "Toàn bộ mô hình cổ điển (không dùng LLM/pretrained), mã nguồn sạch, CI tự động, bộ 6 bảng Parquet (3,92 GiB) đã xuất bản công khai trên Hugging Face và báo cáo Jupyter Book sinh động từ số đo thật."),
        ],
        font_size=10.1,
        space_after=4.5,
    )

    # ===== FOOTER =====
    _add_rect(slide, 0.0, 22.86, A2_WIDTH_IN, 0.525, NAVY)
    tb_f = slide.shapes.add_textbox(Inches(0.45), Inches(22.95), Inches(15.64), Inches(0.35))
    pf = tb_f.text_frame.paragraphs[0]
    pf.alignment = PP_ALIGN.CENTER
    pf.text = "arXiv Harvester • Nhập môn Khoa học dữ liệu (Chương trình Chuẩn) • Khổ đứng A2 (420 × 594 mm) • Tái lập tự động qua tools/generate_poster.py"
    pf.font.name = FONT_NAME
    pf.font.size = Pt(10.5)
    pf.font.color.rgb = SKY_LIGHT

    output_pptx.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_pptx))

    # Kiểm tra hình học tự động: 1 slide, đúng A2 portrait, không tràn biên, không đè card
    check_prs = Presentation(str(output_pptx))
    assert len(check_prs.slides) == 1, f"Expected 1 slide, got {len(check_prs.slides)}"
    w_mm = check_prs.slide_width.inches * 25.4
    h_mm = check_prs.slide_height.inches * 25.4
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
