"""Build the 25,000-paper, 5-member Vietnamese Jupyter Book (M1 & M2) from Colab CPU outputs."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys
from textwrap import dedent

import nbformat

SOURCE_REPO = "https://github.com/NguyenQuocDat06-AI/arxiv-harvester"
BOOK_URL = "https://nguyenquocdat06-ai.github.io/arxiv-harvester-book/"
QA_URL = "https://docs.google.com/spreadsheets/d/11UDWf52DitCDrV386WkYK0ZySqTGQSCRnEwQ37u9uyQ/edit"
M1_STMT = "https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/"
M2_STMT = "https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/"

MEMBERS_META = [
    ("24120282", "DAT", "Nguyễn Quốc Đạt", "2412.18848 - 2501.02641"),
    ("24120237", "TUAN", "Nguyễn Đình Tuấn", "2502.03235 - 2502.08234"),
    ("24120438", "TAN", "Trần Nguyên Tân", "2407.12839 - 2407.17838"),
    ("24120470", "TRI", "Dương Phan Minh Trí", "2406.17938 - 2407.02838"),
    ("24120474", "TRIET", "Trịnh Vỹ Triết", "2406.12938 - 2406.17937"),
]

COMMON_CELL = """
from pathlib import Path
import json
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown
data = json.loads((Path.cwd().parent / 'report_summary.json').read_text(encoding='utf-8'))
scope, m1, m2, bench = data['scope'], data['m1'], data['m2'], data['m2_benchmark']
plt.rcParams.update({'figure.figsize': (9.2, 4.2), 'axes.spines.top': False, 'axes.spines.right': False, 'figure.dpi': 120})
print(f"Toàn nhóm (5 thành viên): {scope['papers']:,} paper / {scope['versions']:,} version | Cập nhật: {data['report_date']}")
""".strip()


def md(text: str):
    cleaned = dedent(text).strip()
    cleaned = cleaned.replace(r"\[", "\n$$\n").replace(r"\]", "\n$$\n")
    cleaned = cleaned.replace(r"\(", "$").replace(r"\)", "$")
    return nbformat.v4.new_markdown_cell(cleaned)


def code(text: str):
    return nbformat.v4.new_code_cell(dedent(text).strip(), metadata={"tags": ["hide-input"]})


def ref_cell(stage: str, files: tuple[str, ...]):
    stmt = M1_STMT if stage == "M1" else M2_STMT
    lines = [
        f"- [Đặc tả chính thức {stage}]({stmt}).",
        "- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html) & [Terms of Use](https://info.arxiv.org/help/api/tou.html).",
        "- [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs/graph).",
        *[f"- Mã nguồn triển khai: [{f}]({SOURCE_REPO}/blob/main/{f})." for f in files],
    ]
    return md("## Tài liệu và mã nguồn tham chiếu\n\n" + "\n".join(lines))


def build_report_summary(workspace: Path) -> dict:
    team_dir = workspace / "team_25000"
    agg = json.loads((team_dir / "book_aggregates_25000.json").read_text(encoding="utf-8"))
    cs = json.loads((team_dir / "consolidation_summary.json").read_text(encoding="utf-8"))
    bm = json.loads((team_dir / "m2_benchmark_sessions.json").read_text(encoding="utf-8"))
    overall_m1 = json.loads((team_dir / "m1_merged/overall_stats.json").read_text(encoding="utf-8"))
    val = json.loads((team_dir / "parsed/project_validation.json").read_text(encoding="utf-8"))
    m2_stats = json.loads((team_dir / "parsed/stats.json").read_text(encoding="utf-8"))
    manifest_rows = json.loads((team_dir / "parsed/manifest.json").read_text(encoding="utf-8"))

    # Per-member consolidated table + M2 phase sums (without leaking internal paths/run_ids)
    per_member = []
    phase_totals: dict[str, dict[str, float | int]] = {}
    session_by_rev_or_time = {
        round(s["profiler_sec"], 3): s for s in bm.get("sessions", [])
    }

    for mssv, short, full_name, id_range in MEMBERS_META:
        st = json.loads((workspace / f"full_{mssv}/stats.json").read_text(encoding="utf-8"))
        aud = json.loads((workspace / f"full_{mssv}/source_audit.json").read_text(encoding="utf-8"))
        sc = st["status_counts"]
        tex_v = st["versions_with_tex"]
        succ_v = sc.get("success", 0)
        part_v = sc.get("partial", 0)
        dd = st["deduplication"]
        for pname, pinfo in (st.get("phases") or {}).items():
            entry = phase_totals.setdefault(pname, {"elapsed_sec": 0.0, "calls": 0})
            entry["elapsed_sec"] += float(pinfo.get("elapsed_sec", 0.0))
            entry["calls"] += int(pinfo.get("calls", 0))
        mem = st.get("memory") or {}
        per_member.append({
            "member": short,
            "full_name": full_name,
            "student_id": mssv,
            "id_range": id_range,
            "publications": st["publications"],
            "versions": st["versions"],
            "tex_verified": (aud.get("reasons") or {}).get("tex_verified", tex_v),
            "success": succ_v,
            "partial": part_v,
            "empty_no_tex": sc.get("empty_no_tex", 0),
            "error": sc.get("error", 0),
            "error_missing_source": sc.get("error_missing_source", 0),
            "tex_success_rate": succ_v / tex_v if tex_v else None,
            "tex_parsed_rate": (succ_v + part_v) / tex_v if tex_v else None,
            "elements_before": dd["elements"]["before"],
            "elements_after": dd["elements"]["after"],
            "elements_reduction": dd["elements"]["reduction_rate"],
            "bibtex_before": dd["bibtex"]["before"],
            "bibtex_after": dd["bibtex"]["after"],
            "bibtex_reduction": dd["bibtex"]["reduction_rate"],
            "unresolved_cites": st.get("unresolved_cites", 0),
            "bibliography_conflicts": st.get("bibliography_conflicts", 0),
            "runtime_sec": st["runtime_sec"],
            "avg_sec_per_pub": st.get("avg_sec_per_processed_publication"),
            "peak_rss_mib": mem.get("peak_rss_mb"),
            "os_reported_peak_rss_mib": mem.get("os_reported_peak_rss_mb"),
            "avg_rss_mib": mem.get("avg_rss_mb"),
            "final_output_bytes": st.get("final_output_bytes"),
            "disk_peak_bytes": (st.get("disk") or {}).get("peak_bytes"),
            "final_disk_bytes": (st.get("disk") or {}).get("final_bytes"),
            "colab_cpu": bool((st.get("environment") or {}).get("is_google_colab") and (st.get("environment") or {}).get("cpu_only")),
        })

    # Coverage distribution across all 25,000 publications (aggregated, zero IDs!)
    cov_rows = m2_stats.get("publication_coverage") or []
    tiers = Counter()
    parsed_cov_bins = Counter()
    for row in cov_rows:
        exp = row["expected_versions"]
        succ = row["success_versions"]
        part = row["partial_versions"]
        emp = row["empty_versions"]
        err = row["error_versions"]
        tex_c = row["versions_with_tex"]
        if emp == exp:
            tiers["Mọi version empty (PDF-only / no LaTeX)"] += 1
            parsed_cov_bins["Không có TeX (chỉ empty)"] += 1
        elif err > 0:
            tiers["Có ít nhất 1 version lỗi/thiếu nguồn"] += 1
        elif part > 0:
            tiers["Parsed đủ (không lỗi, có partial)"] += 1
        elif succ + emp == exp:
            tiers["Hoàn toàn sạch (mọi version success/empty)"] += 1
        else:
            tiers["Khác"] += 1

        if emp < exp:
            pc = row["parsed_version_coverage"]
            if pc == 1.0:
                parsed_cov_bins["100% version TeX parse được"] += 1
            elif pc >= 0.5:
                parsed_cov_bins["50% - <100%"] += 1
            elif pc > 0.0:
                parsed_cov_bins[">0% - <50%"] += 1
            else:
                parsed_cov_bins["0% (lỗi/thiếu hết)"] += 1

    # Diagnostic categories across all 41,498 versions
    diag_cats = Counter()
    for row in manifest_rows:
        cats = set()
        for msg in row.get("diagnostics", []):
            if "bibliograph" in msg:
                cats.add("Bibliography thiếu / không đọc được / trùng khóa")
            elif "missing include" in msg:
                cats.add("Include thiếu hoặc tên file có dấu chấm phụ")
            elif "compilation root" in msg:
                cats.add("Compilation root mơ hồ / không tìm thấy root")
            elif "include" in msg:
                cats.add("Include động / không hỗ trợ")
            elif "item" in msg or "environment" in msg:
                cats.add("Lệnh \\item / môi trường TeX tùy biến")
            else:
                cats.add("Lỗi / diagnostic cấu trúc khác (Unclosed group, self-edge...)")
        if row.get("unresolved_cites"):
            cats.add("Citation key chưa resolve được sau hợp nhất")
        if row["status"] == "error_missing_source":
            cats.add("Thiếu nguồn M1 (HTTP 404 hoặc 11 ver pending)")
        diag_cats.update(cats)

    # Pilot v1 -> v2 comparison
    pv1 = json.loads((workspace / "pilot_24120282/stats.json").read_text(encoding="utf-8"))
    pv2 = json.loads((workspace / "pilot_24120282_v2/stats.json").read_text(encoding="utf-8"))
    pilot_cmp = {
        "papers": 250,
        "versions": pv2["versions"],
        "v1": {
            "status_counts": pv1["status_counts"],
            "tex_success_rate": pv1["status_counts"]["success"] / pv1["versions_with_tex"],
            "unresolved_cites": pv1["unresolved_cites"],
            "runtime_sec": pv1["runtime_sec"],
            "avg_sec_per_pub": pv1["avg_sec_per_processed_publication"],
            "peak_rss_mb": pv1["memory"]["peak_rss_mb"],
            "avg_rss_mb": pv1["memory"]["avg_rss_mb"],
        },
        "v2": {
            "status_counts": pv2["status_counts"],
            "tex_success_rate": pv2["status_counts"]["success"] / pv2["versions_with_tex"],
            "unresolved_cites": pv2["unresolved_cites"],
            "runtime_sec": pv2["runtime_sec"],
            "avg_sec_per_pub": pv2["avg_sec_per_processed_publication"],
            "peak_rss_mb": pv2["memory"]["peak_rss_mb"],
            "avg_rss_mb": pv2["memory"]["avg_rss_mb"],
            "deduplication": pv2["deduplication"],
        },
    }

    # Sanitize sessions (preserve exact stats without file paths or run IDs)
    short_by_id = {m: s for m, s, _, _ in MEMBERS_META}
    sanitized_sessions = []
    for idx, row in enumerate(per_member, 1):
        match_s = session_by_rev_or_time.get(round(row["runtime_sec"], 3), {})
        sanitized_sessions.append({
            "session": f"S{idx} ({row['member']})",
            "member": row["member"],
            "status": match_s.get("status", "completed_with_errors"),
            "colab_cpu": row["colab_cpu"],
            "cpu_count_logical": match_s.get("cpu_count_logical", 2),
            "python_version": match_s.get("python_version", "3.13.18"),
            "processed_attempts": row["publications"],
            "publications_reused": 0,
            "profiler_sec": row["runtime_sec"],
            "avg_sec_per_pub": row["avg_sec_per_pub"],
            "peak_rss_mib": row["peak_rss_mib"],
            "avg_rss_mib": row["avg_rss_mib"],
            "peak_disk_bytes": row["disk_peak_bytes"],
            "final_disk_bytes": row["final_disk_bytes"],
            "final_output_bytes": row["final_output_bytes"],
        })

    # Sanitize M1 overall phases + resources (no paths)
    m1_section = {
        **agg["m1"],
        "avg_versions_per_paper": overall_m1.get("avg_versions_per_paper"),
        "paper_crawl_success_rate": overall_m1.get("paper_crawl_success_rate"),
        "source_version_coverage_rate": overall_m1.get("source_version_coverage_rate"),
        "total_source_size_before_bytes": overall_m1.get("total_source_size_before_bytes"),
        "total_source_size_after_bytes": overall_m1.get("total_source_size_after_bytes"),
        "duplicate_publications_removed": overall_m1.get("duplicate_publications_removed"),
        "duplicate_references_removed": overall_m1.get("duplicate_references_removed"),
        "orphan_references_count": overall_m1.get("orphan_references_count"),
        "phases_aggregated": overall_m1.get("phases_aggregated"),
        "colab_sessions": agg.get("m1_colab_sessions", []),
        "max_member_peak_rss_mb": (overall_m1.get("resource_performance") or {}).get("peak_rss_mb"),
        "weighted_avg_rss_mb": (overall_m1.get("resource_performance") or {}).get("weighted_avg_rss_mb"),
    }

    return {
        "report_date": "2026-11-22",
        "scope": {
            "papers": cs["m1_publications"],
            "versions": cs["m2_versions"],
            "group_assigned": 25000,
            "member_assigned": 5000,
            "members": 5,
            "archives_used": 1713,
            "selection": "Toàn bộ dải 25.000 bài của 5 thành viên (DAT, TUAN, TAN, TRI, TRIET); TRI đã được --resume trên Google Colab CPU từ 4.425 lên 5.000 bài trước khi chạy M2.",
        },
        "m1": m1_section,
        "m2": {
            "status": m2_stats["status"],
            "code_hash": m2_stats["code_hash"],
            "status_counts": m2_stats["status_counts"],
            "versions_with_tex": m2_stats["versions_with_tex"],
            "versions_with_unmeasured_counts": m2_stats["versions_with_unmeasured_counts"],
            "unresolved_cites": m2_stats["unresolved_cites"],
            "bibliography_conflicts": m2_stats["bibliography_conflicts"],
            "deduplication": m2_stats["deduplication"],
            "rows": val["m2"]["rows"],
            "structural_valid": val["structural_valid"],
            "processing_complete": val["processing_complete"],
            "validation_errors": val["errors"],
            "coverage_fraction": val["coverage"]["fraction"],
            "missing_versions": val["coverage"]["missing_versions"],
            "per_member": per_member,
            "coverage_tiers": dict(tiers),
            "parsed_coverage_buckets": dict(parsed_cov_bins),
            "diagnostic_categories": dict(diag_cats.most_common()),
            "top_diagnostics": (m2_stats.get("diagnostics") or [])[:15],
            "pilot_v1_vs_v2": pilot_cmp,
        },
        "m2_benchmark": {
            "environment": {
                "platform": "Linux x86_64 (Google Colab CPU Standard)",
                "python_version": "3.13.18",
                "is_google_colab": True,
                "cpu_only": True,
                "cpu_count_logical": 2,
                "total_memory_mb": 12975.52,
                "code_hash": m2_stats["code_hash"],
            },
            "sessions": sanitized_sessions,
            "totals": {
                "all_sessions_colab_cpu": bm["all_sessions_colab_cpu"],
                "sessions_overlap": bm["sessions_overlap"],
                "duplicate_run_files_skipped": bm["duplicate_run_files_skipped"],
                "processed_attempts": bm["processed_attempts"],
                "unique_publications": bm["unique_publications"],
                "total_profiler_sec": bm["total_profiler_sec"],
                "avg_sec_per_unique_publication": bm["avg_sec_per_unique_publication"],
                "max_session_peak_rss_mib": bm["max_session_peak_rss_mib"],
                "session_time_weighted_avg_rss_mib": bm["session_time_weighted_avg_rss_mib"],
                "max_session_peak_disk_bytes": bm["max_session_peak_disk_bytes"],
                "final_output_bytes": bm["final_output_bytes"],
            },
            "phases_aggregated": {k: {"elapsed_sec": round(v["elapsed_sec"], 3), "calls": v["calls"]} for k, v in phase_totals.items()},
            "resource_profiles": agg.get("m2_resource_profiles", {}),
        },
    }


def _make_nb(cells):
    nb = nbformat.v4.new_notebook(cells=cells)
    nb.metadata.kernelspec = {"display_name": "Python 3", "language": "python", "name": "python3"}
    return nb


def chapter_builders():
    def m1_overview():
        return [
            md("""
            # Milestone 1: Thu thập dữ liệu (25.000 bài báo)

            ## Mục tiêu và quy mô toàn nhóm

            Milestone 1 thu thập metadata theo từng paper (đơn vị thống kê citation/metadata), mã nguồn LaTeX/BibTeX/BBL theo từng `(paper, version)` (đơn vị tải nguồn và audit), cùng mạng lưới trích dẫn từ Semantic Scholar cho toàn bộ **25.000 arXiv ID** của 5 thành viên (5.000 bài/thành viên).

            Trước khi chạy Milestone 2, thành viên `TRI (24120470)` vốn mới có `4.425/5.000` bài do hết ngân sách thời gian 11,5 giờ ở lần crawl trước đã được chạy tiếp `--resume` hoàn toàn trên **Google Colab CPU-only**, kéo đủ `5.000/5.000` bài và xác minh `8.338/8.338` version nguồn.
            """),
            code(COMMON_CELL),
            code("""
            display(Markdown('**Bảng M1.1. Tổng quan corpus hợp nhất 5 thành viên sau khử trùng.**'))
            display(pd.DataFrame([
                ('Tổng ID được giao (5 thành viên)', scope['group_assigned'], 'paper'),
                ('Số publication hợp nhất (0 trùng lặp)', scope['papers'], 'paper'),
                ('Tổng số version ghi nhận', scope['versions'], 'version'),
                ('Chuỗi archive backup đã xác minh SHA-256', scope['archives_used'], 'archive'),
                ('Working references (0 mồ côi)', m1['working_reference_rows'], 'cạnh trích dẫn'),
                ('Course export references (có đích arXiv)', m1['arxiv_reference_rows'], 'cạnh trích dẫn'),
            ], columns=['Chỉ tiêu', 'Số lượng', 'Đơn vị']))
            """),
            code("""
            sa = m1['source_audit']
            metrics = pd.DataFrame([
                ('Version có TeX đã xác minh', sa.get('tex_verified', 0), scope['versions']),
                ('Version xác minh hợp lệ (gồm empty PDF-only/no-LaTeX)', m1['source_verified'], scope['versions']),
                ('Paper đủ 100% version nguồn xác minh', m1['papers_with_all_sources_verified'], scope['papers']),
                ('Paper có kết quả S2 (success hoặc empty xác nhận)', m1['verified_reference_papers'], scope['papers']),
                ('Paper đủ cả nguồn xác minh lẫn S2', m1['papers_with_sources_and_s2_verified'], scope['papers']),
            ], columns=['Chỉ tiêu', 'Đạt', 'Mẫu số'])
            metrics['Tỷ lệ (%)'] = (100 * metrics['Đạt'] / metrics['Mẫu số']).round(2)
            display(Markdown('**Bảng M1.2. Độ phủ nguồn và references trên toàn bộ 25.000 bài.**'))
            display(metrics)
            plot = metrics.iloc[2:].copy()
            ax = plot.plot.barh(x='Chỉ tiêu', y='Tỷ lệ (%)', legend=False, xlim=(0, 114), color='#2f628e')
            for i, row in enumerate(plot.to_dict('records')):
                ax.text(row['Tỷ lệ (%)'] + 1, i, f"{row['Đạt']:,}/{row['Mẫu số']:,}", va='center', fontsize=9)
            ax.set_xlabel('Tỷ lệ paper (%)'); ax.set_ylabel('')
            plt.tight_layout(); plt.show()
            """),
            ref_cell("M1", ("src/crawler/main.py", "src/crawler/merge_shards.py", "src/crawler/validate_sources.py")),
        ]

    def ch01():
        return [
            md("""
            # 1. Discovery và phân bố version (25.000 bài)

            ## 1.1 Phân giải arXiv ID và lịch sử revision

            arXiv Atom API được truy vấn theo lô 50-100 ID/lần (tối thiểu 3 giây/request). Mỗi paper giữ danh sách `versions` từ `v1` tới `vN`; `published` gắn cho `v1` và `updated` cho version mới nhất. Với các revision trung gian chưa biết timestamp, pipeline giữ `null` thay vì suy đoán.
            """),
            code(COMMON_CELL),
            code("""
            hist = pd.Series({int(k): v for k, v in m1['version_histogram'].items()}).sort_index()
            display(Markdown('**Bảng 1.1. Phân bố số version trên mỗi publication (25.000 bài).**'))
            display(hist.rename_axis('Số version/bài').to_frame('Số bài báo'))
            ax = hist.plot.bar(color='#2f628e', xlabel='Số version / bài báo', ylabel='Số bài báo', title='Phân bố revision trên 25.000 bài báo')
            plt.tight_layout(); plt.show()
            display(pd.Series(m1['metadata_missing_fraction'], name='Tỷ lệ thiếu (0-1)').to_frame())
            display(Markdown(f"Trung bình **{scope['versions']/scope['papers']:.2f} version/bài** "
                             f"({m1['missing_version_dates']:,} / {scope['versions']:,} mốc ngày revision trung gian chưa có từ Atom API)."))
            """),
            ref_cell("M1", ("src/crawler/id_range.py", "src/crawler/discovery.py", "src/crawler/version_history.py")),
        ]

    def ch02():
        return [
            md(r"""
            # 2. Tải nguồn, lọc nội dung và audit độc lập

            ## 2.1 Chuẩn hóa tập nguồn TeX/BibTeX/BBL

            Mỗi revision `vN` được tải riêng bằng `src/<id>vN` với nhịp tối thiểu 3 giây. Downloader giải nén qua staging, chỉ giữ mã nguồn văn bản (`.tex`, `.bib` và `.bbl` phụ trợ theo QA) và loại bỏ file ảnh/PDF nhị phân để giảm dung lượng lưu trữ trong khi vẫn giữ nguyên các lệnh `\figure`/`\table`.

            ## 2.2 Kết quả source audit toàn nhóm (41.498 version)
            """),
            code(COMMON_CELL),
            code("""
            sa = pd.Series(m1['source_audit'], name='Số version')
            display(sa.to_frame())
            cmap = {'tex_verified': '#34785a', 'empty_verified': '#768a9a', 'not_found_verified': '#b5534a', 'source_pending_or_failed': '#bd8b25'}
            ax = sa.plot.bar(color=[cmap.get(k, '#2f628e') for k in sa.index], title='Phân loại source audit trên 41.498 version', ylabel='Số version')
            for i, val in enumerate(sa):
                ax.text(i, val + 400, f'{val:,}', ha='center', fontsize=9)
            ax.set_ylim(0, max(sa) * 1.12)
            plt.tight_layout(); plt.show()
            df_size = pd.DataFrame([{
                'Số bài đủ TeX để đo giảm dung lượng': m1['eligible_size_papers'],
                'TB trước lọc (MiB/bài)': round(m1['mean_before_bytes'] / 1048576, 3),
                'TB sau lọc TeX/Bib (MiB/bài)': round(m1['mean_after_bytes'] / 1048576, 3),
                'Tỷ lệ giảm dung lượng': f"{m1['source_reduction']:.2%}",
                'Tổng corpus sau lọc (GiB)': round(m1['total_source_size_after_bytes'] / 1024**3, 2),
            }])
            display(df_size.T.rename(columns={0: 'Giá trị'}))
            """),
            ref_cell("M1", ("src/crawler/source_downloader.py", "src/crawler/validate_sources.py", "src/crawler/drive_backup.py")),
        ]

    def ch03():
        return [
            md("""
            # 3. Thu thập references và độ phủ Semantic Scholar

            ## 3.1 Kết quả truy vấn và tách hai lớp bảng references

            Semantic Scholar được truy vấn theo batch kèm phân trang kiểm chứng với `referenceCount`. Bảng working `references.parquet` giữ mọi trích dẫn (976.351 dòng), còn bảng `course_export/references.parquet` lọc các cạnh có `ref_arxiv_id` hợp lệ (456.149 cạnh) theo chuẩn 6+6 cột của môn học.
            """),
            code(COMMON_CELL),
            code("""
            rs = pd.Series(m1['reference_status'], name='Số bài báo')
            display(rs.to_frame())
            ax = rs.plot.barh(color='#2f628e', title='Trạng thái thu thập references theo publication', xlabel='Số bài báo')
            for i, val in enumerate(rs):
                ax.text(val + 150, i, f'{val:,}', va='center', fontsize=9)
            ax.set_xlim(0, max(rs) * 1.15)
            plt.tight_layout(); plt.show()
            miss = pd.Series(m1['references_missing_fraction'], name='Tỷ lệ thiếu (trên 976.351 dòng)')
            display(miss.to_frame())
            miss.plot.bar(ylim=(0, 1.0), color='#b57b36', title='Tỷ lệ trường null trên bảng working references', ylabel='Tỷ lệ thiếu')
            plt.tight_layout(); plt.show()
            display(Markdown(f"**24.277 / 25.000 bài ({m1['verified_reference_papers']/scope['papers']:.2%})** có kết quả S2 xác minh (`success`/`empty`), "
                             f"trung bình **{m1['mean_references_verified_papers']:.2f} references/bài**."))
            """),
            ref_cell("M1", ("src/crawler/reference_scraper.py", "src/crawler/reference_batch.py", "src/crawler/observations.py")),
        ]

    def ch04():
        return [
            md("""
            # 4. Mô hình dữ liệu 5 bảng và kiểm chuẩn toàn cục (25.000 bài)

            ## 4.1 Cấu trúc 5 bảng M1-M2 và kết quả `validate_project`

            Toàn bộ dữ liệu hợp nhất của 5 thành viên gồm 2 bảng M1 (`papers`, `references`) và 3 bảng M2 (`elements`, `hierarchy`, `bibtex`) được kiểm tra đồng thời bởi `src/parser/validation.py` bằng SQLite key-index trên đĩa cho toàn bộ 25.000 bài báo / 41.498 version.
            """),
            code(COMMON_CELL),
            code("""
            for name, rows in m1['schemas'].items():
                display(Markdown(f"**Schema bảng `{name}`**"))
                display(pd.DataFrame(rows))
            row_summary = pd.DataFrame([
                {'Giai đoạn': 'M1', 'Bảng': 'papers (course)', 'Số dòng': scope['papers']},
                {'Giai đoạn': 'M1', 'Bảng': 'references (course)', 'Số dòng': m1['arxiv_reference_rows']},
                {'Giai đoạn': 'M2', 'Bảng': 'elements', 'Số dòng': m2['rows']['elements']},
                {'Giai đoạn': 'M2', 'Bảng': 'hierarchy', 'Số dòng': m2['rows']['hierarchy']},
                {'Giai đoạn': 'M2', 'Bảng': 'bibtex', 'Số dòng': m2['rows']['bibtex']},
            ])
            display(Markdown('**Bảng 4.1. Tổng số bản ghi của 5 bảng hợp nhất (25.000 bài).**'))
            display(row_summary)
            display(pd.DataFrame([{
                'structural_valid': m2['structural_valid'],
                'processing_complete': m2['processing_complete'],
                'expected_versions': scope['versions'],
                'recorded_versions': scope['versions'],
                'missing_versions': m2['missing_versions'],
                'validation_errors': len(m2['validation_errors']),
            }]))
            """),
            ref_cell("M2", ("src/crawler/storage.py", "src/parser/storage.py", "src/parser/validation.py", "tools/m2_team_consolidator.py")),
        ]

    def ch05():
        return [
            md("""
            # 5. Số đo crawler M1 trên Google Colab CPU-only

            Tổng hợp các phiên chạy Google Colab CPU của 5 thành viên ở giai đoạn M1 (bao gồm phiên `--resume` của `TRI` kéo nốt 575 ID còn thiếu + sửa nguồn trên Colab CPU trước khi bước vào M2).
            """),
            code(COMMON_CELL),
            code("""
            df_m1 = pd.DataFrame(m1['colab_sessions'])
            display(Markdown('**Bảng 5.1. Các phiên crawler M1 trên Google Colab CPU-only.**'))
            display(df_m1)
            phases = pd.DataFrame(m1['phases_aggregated']).T.sort_values('elapsed_sec')
            display(Markdown('**Bảng 5.2. Tổng hợp thời gian theo pha M1 (từ 4 thành viên full shard stats dùng được).**'))
            display(phases)
            phases['elapsed_sec'].plot.barh(color='#2f628e', xlabel='Tổng giây cộng dồn', title='Thời gian pha crawler M1 (các pha chạy nền gối đầu)')
            plt.tight_layout(); plt.show()
            """),
            ref_cell("M1", ("src/crawler/profiler.py", "src/crawler/benchmark_sessions.py", "tools/m1_colab_tri_resume.py")),
        ]

    def m2_overview():
        return [
            md("""
            # Milestone 2: Phân tích cấu trúc, chuẩn hóa và khử trùng (25.000 bài)

            ## Kết quả toàn nhóm trên Google Colab CPU-only

            Toàn bộ **25.000 bài báo / 41.498 version** của 5 thành viên đã được chạy parser cold (0 reuse, `code_hash=cf2de7a143c8...`) qua 5 phiên **Google Colab CPU-only** tuần tự, sau đó gộp và kiểm chuẩn 5 bảng bằng [m2_team_consolidator.py](https://github.com/NguyenQuocDat06-AI/arxiv-harvester/blob/main/tools/m2_team_consolidator.py).
            """),
            code(COMMON_CELL),
            code("""
            labels = {'success': 'Success', 'partial': 'Partial', 'empty_no_tex': 'Empty (PDF-only / no-LaTeX)',
                      'error': 'Lỗi parser / root', 'error_missing_source': 'Thiếu nguồn M1 (404/pending)'}
            st_df = pd.DataFrame([{'Trạng thái': lbl, 'Số version': m2['status_counts'].get(k, 0)} for k, lbl in labels.items()])
            st_df['Tỷ lệ (%)'] = (100 * st_df['Số version'] / scope['versions']).round(2)
            display(Markdown('**Bảng M2.1. Phân bố trạng thái parser trên 41.498 version.**'))
            display(st_df)
            ax = st_df.plot.barh(x='Trạng thái', y='Số version', legend=False, color=['#34785a', '#bd8b25', '#768a9a', '#b5534a', '#9b6259'])
            for i, r in enumerate(st_df.to_dict('records')):
                ax.text(r['Số version'] + 500, i, f"{r['Số version']:,} ({r['Tỷ lệ (%)']}%)", va='center', fontsize=9)
            ax.set_xlim(0, max(st_df['Số version']) * 1.24); ax.set_ylabel('')
            plt.tight_layout(); plt.show()
            """),
            code("""
            pm = pd.DataFrame(m2['per_member'])
            cols = ['member', 'id_range', 'publications', 'versions', 'success', 'partial', 'empty_no_tex', 'error', 'tex_success_rate', 'tex_parsed_rate', 'runtime_sec', 'avg_sec_per_pub', 'peak_rss_mib']
            view = pm[cols].copy()
            view['tex_success_rate'] = (100 * view['tex_success_rate']).round(2)
            view['tex_parsed_rate'] = (100 * view['tex_parsed_rate']).round(2)
            display(Markdown('**Bảng M2.2. Kết quả và hiệu năng M2 theo từng thành viên (Colab CPU-only).**'))
            display(view)
            dd = pd.DataFrame(m2['deduplication']).T
            dd['removed'] = dd['before'] - dd['after']
            display(Markdown('**Bảng M2.3. Khử trùng toàn bộ 25.000 bài sau chuẩn hóa.**'))
            display(dd)
            """),
            ref_cell("M2", ("src/parser/main.py", "src/parser/statistics.py", "tools/m2_colab_runner.py", "tools/m2_team_consolidator.py")),
        ]

    def ch06():
        return [
            md(r"""
            # 6. Gathering và dựng cây hierarchy theo version

            ## 6.1 Thiết kế compilation path và phân cấp AST/Tree

            - **Multi-file Gathering** (`gather.py`): quét các tệp `.tex` tìm `\documentclass`/`\documentstyle`. Khi có nhiều ứng viên root, thuật toán đối chiếu tiêu đề từ metadata M1 (hoặc dùng `--root-overrides`); bỏ qua các lệnh nằm sau comment `%` và đi theo `\input`/`\include` bắc cầu từ thư mục biên dịch, dừng tại `\endinput` hoặc `\end{document}` để loại file `.tex` thừa.
            - **Cây phân cấp** (`hierarchy.py`): nút gốc là `document`, tới `chapter`/`section`/`subsection`..., `paragraph`, `list`/`item`, và lá nhỏ nhất là `sentence`, `block_formula`, `figure` (gộp cả `table` thành `figure`). Bộ tách câu bảo vệ nội dung trong toán `$...$`, lệnh TeX, URL, số thập phân (`3.14`) và viết tắt (`e.g.`, `i.e.`, `et al.`, `Fig. 1`). Mục References/Bibliography tách khỏi cây; `Acknowledgements` và `Appendix` (`\section*`, `\appendix`) được giữ lại.

            ## 6.2 Ví dụ thực thi gathering & hierarchy từ code thật
            """),
            code(COMMON_CELL),
            code(r'''
            import tempfile
            from parser.gather import gather
            from parser.hierarchy import parse_hierarchy
            main_tex = r"""\documentclass{article}
            \title{Demo Multi-file Paper}
            \begin{document}
            % \input{ignored_comment}
            \input{sections/intro}
            \section*{Acknowledgements}
            We thank the team.
            \appendix
            \section{Appendix Proof}
            Extra proof detail.
            \section*{References}
            \begin{thebibliography}{9}
            \bibitem{k1} A. Author. Title. 2020.
            \end{thebibliography}
            \end{document}"""
            intro_tex = r"""\section{Introduction}
            First sentence with Fig. 1 and value 3.14.
            \begin{itemize}\item First point.\item Second point.\end{itemize}
            \begin{align}x + y = z\end{align}
            \begin{table}[htpb]\centering\begin{tabular}{cc}\toprule A & B \\ \midrule 1 & 2 \\ \bottomrule\end{tabular}\end{table}
            """
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); (root / 'sections').mkdir()
                (root / 'main.tex').write_text(main_tex, encoding='utf-8')
                (root / 'sections/intro.tex').write_text(intro_tex, encoding='utf-8')
                (root / 'redundant.tex').write_text('Ignored standalone file.', encoding='utf-8')
                g = gather(root); tree = parse_hierarchy(g.text)
                print('Root:', g.root, '| Compilation path:', g.files, '| Diagnostics:', g.diagnostics + tree.diagnostics)
                display(pd.DataFrame([{'node_id': n.node_id, 'parent_id': n.parent_id, 'kind': n.kind, 'content': n.content[:90]} for n in tree.nodes]))
            '''),
            md(r"""
            ## 6.3 Tác động nâng cấp parser qua Pilot (v1 -> v2) và phân bố 25.000 bài

            Trước khi chạy toàn bộ 25.000 bài, nhóm chạy Pilot phân tầng 250 bài (`536` version) trên Colab CPU, phát hiện và vá 4 nhóm lỗi thực tế (tách nhánh `\cite{{k1},{k2}}`, deduplicate khóa trùng trong cùng version theo độ ưu tiên `.bib > inline > .bbl`, chặn crash khoảng nửa mở `[0, 1)` sau `\item`, phân giải đa root theo tiêu đề M1, mở rộng tập môi trường list như `compactitem`/`enumerate*`/`inparaenum`, tối ưu `parse_bibtex` bằng lazy field parsing cho các file `.bib` khổng lồ như `anthology.bib` 43,8 MB).
            """),
            code("""
            pv = m2['pilot_v1_vs_v2']
            comp = pd.DataFrame({
                'Pilot v1 (trước vá)': pv['v1']['status_counts'],
                'Pilot v2 (sau vá)': pv['v2']['status_counts'],
            }).fillna(0).astype(int)
            display(Markdown('**Bảng 6.1. So sánh Pilot 250 bài / 536 version trên Colab CPU trước & sau nâng cấp parser.**'))
            display(comp)
            comp.plot.bar(title='Tác động nâng cấp parser trên Pilot 250 bài (Colab CPU)', ylabel='Số version')
            plt.tight_layout(); plt.show()

            tiers = pd.Series(m2['coverage_tiers'], name='Số bài báo')
            display(Markdown('**Bảng 6.2. Phân tầng mức độ hoàn thiện trên toàn bộ 25.000 bài.**'))
            display(tiers.to_frame())
            cov_buckets = pd.Series(m2['parsed_coverage_buckets'], name='Số bài báo')
            display(Markdown('**Bảng 6.3. Phân bố tỷ lệ version TeX parse được trên mỗi bài báo (25.000 bài).**'))
            display(cov_buckets.to_frame())
            cov_sorted = cov_buckets.sort_values()
            ax_cov = cov_sorted.plot.barh(color='#2f628e', title='Độ phủ version parse được theo từng bài báo (25.000 bài)', xlabel='Số bài báo')
            for i, v in enumerate(cov_sorted):
                ax_cov.text(v + 250, i, f'{v:,}', va='center', fontsize=9)
            ax_cov.set_xlim(0, cov_sorted.max() * 1.18)
            plt.tight_layout(); plt.show()
            diag = pd.Series(m2['diagnostic_categories'], name='Số version có diagnostic').sort_values()
            ax = diag.plot.barh(color='#b57b36', title='Nhóm diagnostic trên 41.498 version', xlabel='Số version')
            for i, v in enumerate(diag):
                ax.text(v + 120, i, f'{v:,}', va='center', fontsize=9)
            ax.set_xlim(0, diag.max() * 1.18)
            plt.tight_layout(); plt.show()
            """),
            ref_cell("M2", ("src/parser/gather.py", "src/parser/latex.py", "src/parser/hierarchy.py", "src/parser/main.py")),
        ]

    def ch07():
        return [
            md(r"""
            # 7. Chuẩn hóa, trích xuất BibTeX và khử trùng 2 tầng

            ## 7.1 Chuẩn hóa LaTeX & Toán học (`normalize.py`)

            - Gỡ các wrapper trình bày (`\textbf`, `\emph`, ...) giữ lại ngữ nghĩa bên trong; xóa các lệnh bố cục (`\centering`, `\toprule`, `\midrule`, `\bottomrule`, tùy chọn `[htpb]`...).
            - Chuẩn hóa toàn bộ inline math (`$...$`, `\(...\)`) về `$...$`, và toàn bộ block math (`$$...$$`, `\[...\]`, `equation*`, `align`, `gather`, `multline`, ...) về `\begin{equation}...\end{equation}`.

            ## 7.2 Khử trùng 2 tầng xuyên version (`bibliography.py` & `deduplicate.py`)

            - **Tầng 1 - Reference entries**: hợp nhất các bản ghi từ `.bib`, `\bibitem` và fallback `.bbl` theo định danh mạnh (`doi`, `eprint` arXiv) hoặc chữ ký `(title, authors)`, gộp (union) trường mới từ các version sau và **đổi tên mọi lệnh `\cite{}`** (kể cả trong môi trường toán) về khóa đại diện duy nhất.
            - **Tầng 2 - Full-text elements**: chuẩn hóa từng nút trước khi băm SHA-256 theo `(arxiv_id, kind, normalized_content)` để dùng chung `element_id` ở bảng `elements`, giữ riêng từng cạnh `(version, element_id, parent_id)` ở bảng `hierarchy`.
            """),
            code(COMMON_CELL),
            code(r'''
            from parser.normalize import normalize
            from parser.bibliography import parse_bibitems, unify_entries
            from parser.hierarchy import parse_hierarchy
            from parser.deduplicate import deduplicate

            v1_tex = r"""\documentclass{article}\title{Demo}\begin{document}\section{Intro}We study \(a + b\) with \cite{vaswani2017}.\begin{thebibliography}{9}\bibitem{vaswani2017}A. Vaswani.\newblock Attention Is All You Need.\newblock 2017.\end{thebibliography}\end{document}"""
            v2_tex = r"""\documentclass{article}\title{Demo}\begin{document}\section{Intro}We study $a+b$ with \cite{vit_transformer}.\section{Method}New method.\begin{thebibliography}{9}\bibitem{vit_transformer}A. Vaswani.\newblock Attention Is All You Need.\newblock 2017. 10.48550/arXiv.1706.03762.\end{thebibliography}\end{document}"""
            h1, h2 = parse_hierarchy(v1_tex), parse_hierarchy(v2_tex)
            bib_rows, mappings, conflicts = unify_entries('demo', [*parse_bibitems(v1_tex, 1), *parse_bibitems(v2_tex, 2)])
            els, edges, _ = deduplicate('demo', {1: h1, 2: h2}, mappings)
            print('Citation mapping sau gộp 2 version:', mappings)
            display(pd.DataFrame(bib_rows).drop(columns=['arxiv_id']))
            print(f'Elements trước dedup: {len(h1.nodes)+len(h2.nodes)} -> sau dedup: {len(els)} | Cạnh hierarchy 2 version: {len(edges)}')
            '''),
            code("""
            dedup = pd.DataFrame(m2['deduplication']).T
            dedup['removed'] = dedup['before'] - dedup['after']
            dedup['reduction_%'] = (100 * dedup['reduction_rate']).round(2)
            display(Markdown('**Bảng 7.1. Hiệu quả khử trùng xuyên version trên toàn bộ 25.000 bài.**'))
            display(dedup[['before', 'after', 'removed', 'reduction_%']])

            fig, axes = plt.subplots(1, 2, figsize=(10.5, 4))
            for ax, key, title in [(axes[0], 'elements', 'Elements trước/sau dedup (25.000 bài)'),
                                   (axes[1], 'bibtex', 'BibTeX entries trước/sau dedup (25.000 bài)')]:
                vals = [m2['deduplication'][key]['before'], m2['deduplication'][key]['after']]
                bars = ax.bar(['Trước dedup', 'Sau dedup'], vals, color=['#768a9a', '#2f628e'])
                for b, v in zip(bars, vals):
                    ax.text(b.get_x() + b.get_width()/2, v * 1.02, f'{v:,}', ha='center', fontsize=9)
                ax.set_ylim(0, max(vals) * 1.15); ax.set_title(title)
            plt.tight_layout(); plt.show()
            display(Markdown(f"Trên toàn tập 25.000 bài ghi nhận **{m2['unresolved_cites']:,} citation key chưa resolve theo version** "
                             f"và **{m2['bibliography_conflicts']:,} sự kiện xung đột trường bibliography** (giữ nguyên giá trị đầu kèm bản ghi xung đột)."))
            """),
            ref_cell("M2", ("src/parser/normalize.py", "src/parser/bibliography.py", "src/parser/deduplicate.py", "src/parser/statistics.py")),
        ]

    def ch08():
        return [
            md("""
            # 8. Benchmark chính thức Milestone 2 trên Google Colab CPU-only

            ## 8.1 Môi trường đo và tổng hợp 5 phiên liên tiếp

            Toàn bộ **5 phiên full** (mỗi phiên chạy cold **5.000 bài**, `reused=0`) được thực thi tuần tự trên **Google Colab Standard CPU-only** (`is_google_colab=True`, `cpu_only=True`, 2 logical vCPU Intel x86_64, RAM 12.975,52 MB, Python 3.13.18) và tổng hợp bằng `src/crawler/benchmark_sessions.py`.
            """),
            code(COMMON_CELL),
            code("""
            display(pd.Series(bench['environment'], name='Giá trị').to_frame())
            tot = bench['totals']
            display(Markdown('**Bảng 8.1. Tổng hợp benchmark Milestone 2 trên Google Colab CPU-only (25.000 bài).**'))
            display(pd.DataFrame([
                ('Mọi phiên đều là Colab CPU-only', str(tot['all_sessions_colab_cpu'])),
                ('Phiên chạy gối giờ / trùng file stats', f"{tot['sessions_overlap']} / {tot['duplicate_run_files_skipped']}"),
                ('Tổng bài parse mới (cold, reused=0)', f"{tot['unique_publications']:,} bài"),
                ('Tổng thời gian xử lý + validate (5 phiên)', f"{tot['total_profiler_sec']:,.3f} giây (~{tot['total_profiler_sec']/3600:.2f} giờ)"),
                ('Thời gian trung bình mỗi publication', f"{tot['avg_sec_per_unique_publication']:.4f} giây/bài"),
                ('Peak RSS lớn nhất quan sát được', f"{tot['max_session_peak_rss_mib']:.2f} MiB"),
                ('RSS trung bình trọng số thời gian', f"{tot['session_time_weighted_avg_rss_mib']:.2f} MiB"),
                ('Peak disk workspace lớn nhất', f"{tot['max_session_peak_disk_bytes']/1024**3:.2f} GiB"),
                ('Dung lượng 3 bảng Parquet chuẩn hợp nhất', f"{tot['final_output_bytes']:,} byte ({tot['final_output_bytes']/1024**3:.2f} GiB)"),
            ], columns=['Chỉ tiêu', 'Kết quả đo']))
            df_sess = pd.DataFrame(bench['sessions'])
            display(Markdown('**Bảng 8.2. Chi tiết từng phiên Colab CPU của 5 thành viên.**'))
            display(df_sess[['session', 'processed_attempts', 'profiler_sec', 'avg_sec_per_pub', 'peak_rss_mib', 'avg_rss_mib', 'final_output_bytes']])
            """),
            code("""
            phases = pd.DataFrame(bench['phases_aggregated']).T.sort_values('elapsed_sec', ascending=False)
            display(Markdown('**Bảng 8.3. Phân bổ thời gian các pha xử lý M2 (cộng dồn 5 phiên).**'))
            display(phases)

            fig, axes = plt.subplots(1, 2, figsize=(11, 4))
            df_s = pd.DataFrame(bench['sessions'])
            axes[0].bar(df_s['member'], df_s['avg_sec_per_pub'], color='#2f628e')
            axes[0].axhline(bench['totals']['avg_sec_per_unique_publication'], color='#b5534a', linestyle='--', label='TB chung 0,748s/bài')
            axes[0].set(ylabel='Giây / publication', title='Tốc độ trung bình từng thành viên (Colab CPU)')
            axes[0].legend(fontsize=8)
            axes[1].bar(df_s['member'], df_s['peak_rss_mib'], color='#b57b36', label='Peak RSS (MiB)')
            axes[1].bar(df_s['member'], df_s['avg_rss_mib'], color='#34785a', label='Mean RSS (MiB)')
            axes[1].set(ylabel='MiB', title='Mức sử dụng RAM trên Colab CPU')
            axes[1].legend(fontsize=8)
            plt.tight_layout(); plt.show()
            """),
            code("""
            profiles = bench.get('resource_profiles') or {}
            avail = {k: v for k, v in profiles.items() if v and v.get('rows')}
            if avail:
                fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.2))
                for label, prof in avail.items():
                    f = pd.DataFrame(prof['rows'])
                    t_min = f['window_end_sec'] / 60.0
                    axes[0].plot(t_min, f['rss_sample_mean_mib'], label=label, linewidth=1.3)
                    disk_rows = f.dropna(subset=['disk_peak_bytes'])
                    if not disk_rows.empty:
                        axes[1].plot(disk_rows['window_end_sec'] / 60.0, disk_rows['disk_peak_bytes'] / 1024**3, label=label, linewidth=1.3)
                axes[0].set(xlabel='Phút chạy', ylabel='Mean RSS trong cửa sổ 60s (MiB)', title='Diễn biến RAM theo thời gian (Colab CPU)')
                axes[0].legend(fontsize=8)
                axes[1].set(xlabel='Phút chạy', ylabel='Disk workspace (GiB)', title='Dung lượng workspace parsed theo thời gian')
                axes[1].legend(fontsize=8)
                plt.tight_layout(); plt.show()
                display(Markdown('**Hình 8.2. Chuỗi thời gian RSS và đĩa đo từ `resource_samples.jsonl` (4 phiên bật sync đầy đủ: TUAN, TAN, TRI, TRIET; cửa sổ 60s).**'))
            display(Markdown(f"Dung lượng đĩa đỉnh của workspace trên Google Colab CPU-only đạt **{bench['totals']['max_session_peak_disk_bytes']/1024**3:.2f} GiB** (`{bench['totals']['max_session_peak_disk_bytes']:,}` byte) và 3 bảng Parquet đầu ra cuối còn **{bench['totals']['final_output_bytes']/1024**3:.2f} GiB** (`{bench['totals']['final_output_bytes']/1e9:.2f} GB`), nằm trong giới hạn đĩa của Colab."))
            """),
            ref_cell("M2", ("src/parser/main.py", "src/crawler/profiler.py", "src/crawler/benchmark_sessions.py", "tools/m2_colab_runner.py")),
        ]

    def discussion():
        return [
            md("""
            # Thảo luận, phân tích lỗi và kết luận

            ## Những kết quả đạt được trên đủ 25.000 bài báo

            1. **Phủ trọn dải 25.000 bài của cả 5 thành viên**: sau khi chạy `--resume` M1 cho TRI trên Google Colab CPU-only, tập hợp nhất đạt `25.000` publication duy nhất (`0` trùng lặp chéo thành viên), `41.498` version (`41.487` đã audit xác minh), `976.351` working references (`0` mồ côi) và `456.149` cạnh arXiv trong `course_export`.
            2. **Chất lượng parser & khử trùng M2**: trên `38.554` version TeX đã xác minh, parser đạt **85,66% `success`** (`33.025` version) và **97,34% parse được vào cấu trúc** (`37.528` gồm cả `4.503` `partial`), còn `2,66%` (`1.026` version) lỗi; cả `2.764` version `empty_no_tex` trùng khớp với bằng chứng kiểm toán M1. Khử trùng xuyên version giảm `35,04%` số phần tử (`23.099.589 -> 15.006.000`) và `35,83%` số mục BibTeX (`1.834.650 -> 1.177.293`).
            3. **Tính hợp lệ 5 bảng & hiệu năng Colab CPU-only**: `validate_project` xác nhận `structural_valid=True` với `0` lỗi khóa/graph trên `22.532.299` cạnh `hierarchy`. Tổng thời gian parse và validate 25.000 bài cold là **18.692,09 giây** (~5 giờ 12 phút, trung bình **0,7477 giây/bài**), đỉnh RSS toàn phiên **845,34 MiB** (< 7% giới hạn 12,67 GiB của Colab Free) và output 3 bảng Parquet chuẩn còn **3,93 GiB** (`4,22 GB`).

            ## Phân tích nguyên nhân top diagnostics còn lại

            Dưới đây là 15 diagnostic phổ biến nhất trên toàn bộ 41.498 version, cho thấy nguyên nhân `processing_complete=false` dù `structural_valid=True`:
            """),
            code(COMMON_CELL),
            code("""
            top_d = pd.DataFrame(m2['top_diagnostics'])
            display(top_d)
            """),
            md("""
            - **`item outside supported list` (9.087 version)**: phần lớn đến từ macro hoặc gói định nghĩa danh sách/thuật toán không chuẩn ngoài nhóm `itemize`/`enumerate`/`description`/`compactitem`/`inparaenum`/`list`/`trivlist`; parser chuyển trạng thái sang `partial` để giữ lại phần nội dung parse được thay vì bỏ cả version.
            - **`Unclosed TeX group` (285 version) và `unmatched end environment: multline` (90 version)**: dấu ngoặc nhọn không cân bằng trong macro hoặc môi trường toán viết tắt từ tác giả làm dừng nhánh con hiện tại.
            - **`dynamic/unsupported include in main.tex` (164 version) và `missing/unsafe bibliography: references.bib` (57 version)**: macro truyền đường dẫn include động không phải chuỗi tĩnh, hoặc tệp bibliography khai báo trong `.tex` không có mặt trong gói nguồn.
            - **11 version `source_pending_or_failed` của TRIET từ M1** và **169 version HTTP 404** đã xác minh: được ghi là `error_missing_source` (`180` version), không tạo phần tử giả.

            ## Kết luận và hướng cho Milestone 3

            Bộ 5 bảng Parquet (`papers`, `references`, `elements`, `hierarchy`, `bibtex`) của toàn bộ **25.000 bài báo** đã hợp lệ về cấu trúc và khóa ngoại, đủ điều kiện làm đầu vào cho bài toán Reference Matching ở Milestone 3.
            """),
            ref_cell("M2", ("src/parser/validation.py", "tools/m2_team_consolidator.py", "tools/build_team_25000_book.py")),
        ]

    def app_repro():
        return [
            md("""
            # Phụ lục A. Tái lập thực nghiệm và cấu hình Colab CPU-only

            ## A.1 Tái lập báo cáo Jupyter Book

            Notebook đọc số liệu trực tiếp từ `report_summary.json` (chỉ chứa số liệu tổng hợp và ví dụ code minh họa) nên có thể dựng lại ở mọi máy mà không cần tải 22,72 GiB corpus hay khóa API:

            ```bash
            python -m pip install -r requirements.txt
            jupyter-book build . --all -W
            ```

            ## A.2 Tái lập xử lý M2 trên Google Colab CPU-only (từng thành viên & gộp 25.000 bài)

            1. Khởi chạy lần lượt từng thành viên qua `colab_parser_full.ipynb` hoặc `tools/m2_colab_runner.py` trên runtime Colab **CPU Standard** (`nvidia0=False`, `COLAB_TPU_ADDR=None`), cấu hình `config_<MSSV>_full.json`.
            2. Chạy `tools/m2_team_consolidator.py` trên Colab CPU để gộp M1 `merge_shards`, trích batch M2, tính `stats.json` hợp nhất, chạy `src.parser.validation.validate_project` toàn cục 25.000 bài và tổng hợp benchmark nhiều phiên qua `src.crawler.benchmark_sessions`.
            """),
            code(COMMON_CELL),
            code("""
            import sys, importlib.metadata
            print('Python biên dịch Book:', sys.version.split()[0])
            pkgs = ['jupyter-book', 'pandas', 'pyarrow', 'matplotlib', 'nbformat', 'arxiv-harvester']
            rows = []
            for p in pkgs:
                try:
                    ver = importlib.metadata.version(p)
                except importlib.metadata.PackageNotFoundError:
                    ver = 'editable/PYTHONPATH'
                rows.append({'package': p, 'version': ver})
            display(pd.DataFrame(rows))
            """),
            ref_cell("M2", ("colab_parser_full.ipynb", "tools/m2_colab_runner.py", "tools/m2_team_consolidator.py", "tools/extract_book_aggregates_colab.py")),
        ]

    def app_limits():
        return [
            md("""
            # Phụ lục B. Đối chiếu yêu cầu đồ án và giới hạn

            Bảng kiểm tổng hợp toàn bộ tiêu chí của Milestone 1, Milestone 2 và điều chỉnh QA của giảng viên trên quy mô **25.000 bài báo**:
            """),
            code(COMMON_CELL),
            code("""
            sa = m1['source_audit']
            sc = m2['status_counts']
            rows = [
                ('M1', 'Discovery đủ dải 5 thành viên', 'Đạt 25.000 / 25.000 ID', 'Bao gồm --resume M1 cho TRI (24120470) trên Colab CPU'),
                ('M1', 'Audit & giữ nguyên từng version', f"{m1['source_verified']:,} / {scope['versions']:,} version verified", f"Còn 11 version pending/lỗi nguồn từ shard TRIET + {sa.get('not_found_verified',0)} HTTP 404"),
                ('M1', 'References S2 & course export', f"{m1['verified_reference_papers']:,} / {scope['papers']:,} paper S2 xác minh", f"{m1['working_reference_rows']:,} working rows / {m1['arxiv_reference_rows']:,} course arXiv edges"),
                ('M2', 'Multi-file gathering & root', 'Đạt & có override kiểm chứng', '26 version thiếu root; include có dấu chấm phụ hoặc macro động còn partial'),
                ('M2', 'Hierarchy (sentence/math/figure/list)', 'Đạt quy tắc lá/nhánh/loại trừ', '9.087 version có macro \\item ngoài nhóm list chuẩn -> giữ ở partial'),
                ('M2', 'Chuẩn hóa & khử trùng 2 tầng', f"Elements -{m2['deduplication']['elements']['reduction_rate']:.2%}; BibTeX -{m2['deduplication']['bibtex']['reduction_rate']:.2%}", 'Giữ .bbl theo QA và union field + đổi tên \\cite{} xuyên version'),
                ('M2', 'Kiểm chuẩn 5 bảng toàn nhóm', 'structural_valid = True (0 lỗi)', f"Elements {m2['rows']['elements']:,}; Hierarchy {m2['rows']['hierarchy']:,}; BibTeX {m2['rows']['bibtex']:,}"),
                ('M2', 'Benchmark Google Colab CPU-only', 'Đạt (5/5 phiên độc lập, cold)', f"{bench['totals']['total_profiler_sec']:,.2f}s (~{bench['totals']['avg_sec_per_unique_publication']:.4f}s/bài); peak RSS {bench['totals']['max_session_peak_rss_mib']:.2f} MiB"),
                ('Book', 'Jupyter Book động & tiếng Việt', 'Biên dịch --all -W thành công', 'Sinh toàn bộ bảng/biểu đồ khi build; giữ URL cố định'),
            ]
            with pd.option_context('display.max_rows', None, 'display.max_colwidth', 120):
                display(pd.DataFrame(rows, columns=['Mốc', 'Hạng mục', 'Kết quả đo 25.000 bài', 'Ghi chú / giới hạn']))
            """),
            ref_cell("M2", ("README.md", "src/parser/validation.py")),
        ]

    return [
        ("00_m1_overview", m1_overview),
        ("01_discovery_and_versions", ch01),
        ("02_source_download_and_cleaning", ch02),
        ("03_reference_extraction", ch03),
        ("04_schema_and_data_quality", ch04),
        ("05_performance_benchmark", ch05),
        ("00_m2_overview", m2_overview),
        ("06_parsing_and_hierarchy", ch06),
        ("07_standardization_and_deduplication", ch07),
        ("08_parser_benchmark", ch08),
        ("12_discussion_and_conclusion", discussion),
        ("09_reproducibility", app_repro),
        ("10_requirements_and_limitations", app_limits),
    ]


def write_book(workspace: Path, output: Path, do_build: bool = False) -> Path:
    if output.exists():
        shutil.rmtree(output)
    (output / "chapters").mkdir(parents=True)
    (output / "_static").mkdir(parents=True)
    (output / ".github/workflows").mkdir(parents=True)

    summary = build_report_summary(workspace)
    (output / "report_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name, builder in chapter_builders():
        nbformat.write(_make_nb(builder()), output / "chapters" / f"{name}.ipynb")

    (output / "chapters/11_references.md").write_text(dedent(f"""
    # Tài liệu tham khảo

    ## Đề bài và chuẩn kỹ thuật

    1. HCMUS CS Teaching Assistants. [Yêu cầu chung](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/), [Milestone 1 - Crawling]({M1_STMT}), [Milestone 2 - Parsing]({M2_STMT}).
    2. arXiv. [API User's Manual](https://info.arxiv.org/help/api/user-manual.html), [API Terms of Use](https://info.arxiv.org/help/api/tou.html), [Full-text harvesting](https://info.arxiv.org/help/bulk_data.html).
    3. Allen Institute for AI. [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs/graph).
    4. [QA Replies 2627-1]({QA_URL}) của giảng viên môn Nhập môn Khoa học dữ liệu.

    ## Mã nguồn nhóm arXiv Harvester

    - [Repository source chính (GitHub)]({SOURCE_REPO}/tree/main)
    - [Phân công & đóng góp thành viên]({SOURCE_REPO}/blob/main/CONTRIBUTIONS.md)
    - [Script dựng Book 25.000 bài]({SOURCE_REPO}/blob/main/tools/build_team_25000_book.py)
    """).strip() + "\n", encoding="utf-8")

    (output / "chapters/13_teacher_qa.md").write_text(dedent(f"""
    # Phụ lục C. Đối chiếu hướng dẫn QA của giảng viên

    Nguồn đối chiếu: [QA Replies 2627-1]({QA_URL}) - Nhóm học chương trình Chuẩn, trình bày báo cáo bằng tiếng Việt.

    - **[M1 dòng 7]({QA_URL}#gid=0&range=A7:B7) (URL cố định qua các mốc nộp)**: Giữ nguyên địa chỉ `{BOOK_URL}` khi cập nhật báo cáo từ mốc 73 bài tiến độ lên bộ đầy đủ 25.000 bài.
    - **[M1 dòng 13-17]({QA_URL}#gid=0&range=A13:B17) (Benchmark nhiều phiên Colab CPU-only)**: Toàn bộ 5 lượt chạy full M2 (mỗi lượt 5.000 bài, không gối giờ, `reused=0`, cùng `code_hash=cf2de7a1...`) được chạy trên Google Colab CPU-only và tổng hợp qua `src/crawler/benchmark_sessions.py`.
    - **[M1 dòng 19]({QA_URL}#gid=0&range=A19:B19) (Giữ & fallback `.bbl`)**: Downloader giữ lại `.bbl`, và parser giải mã `\\bibitem` trong `<root>.bbl` hoặc bibliography được khai báo khi thiếu `.bib`.
    - **[M1 dòng 20-21]({QA_URL}#gid=0&range=A20:B21) (Nguồn ngày `ref_submission_date`)**: Chấp nhận `publicationDate` từ S2 hoặc ngày lấy qua arXiv ID và lưu rõ provenance.
    - **[M1 dòng 17, 22]({QA_URL}#gid=0&range=A17:B22) (Cấu trúc 2 chương chính M1/M2 & mục con kỹ thuật)**: Book giữ đúng cấu trúc 2 phần M1/M2 kèm thảo luận và 4 phụ lục.
    """).strip() + "\n", encoding="utf-8")

    m2s = summary["m2"]
    bench_tot = summary["m2_benchmark"]["totals"]
    sc = m2s["status_counts"]
    (output / "index.md").write_text(dedent(f"""
    # arXiv Harvester - Báo cáo Milestone 1 và 2 (25.000 bài báo)

    Báo cáo đồ án môn **Nhập môn Khoa học dữ liệu (chương trình Chuẩn)**, cập nhật ngày **{summary['report_date']}** với kết quả **đầy đủ 25.000 bài báo / 41.498 version** của cả 5 thành viên chạy và đo hiệu năng trên **Google Colab CPU-only**.

    ## Tóm tắt kết quả toàn nhóm (25.000 bài)

    | Chỉ tiêu | Kết quả đạt được |
    |---|---:|
    | Tổng số publication hợp nhất (5 thành viên, 0 trùng lặp) | **25.000 / 25.000** |
    | Tổng số version & nguồn đã audit xác minh | **41.487 / 41.498** (TeX: {summary['m1']['source_audit']['tex_verified']:,}; Empty: {summary['m1']['source_audit']['empty_verified']:,}) |
    | References M1 (`working` / `course arXiv`) | **{summary['m1']['working_reference_rows']:,}** (`0` mồ côi) / **{summary['m1']['arxiv_reference_rows']:,}** |
    | M2 parser trên version TeX xác minh | **{sc['success']:,} `success` ({sc['success']/summary['m1']['source_audit']['tex_verified']:.2%})**, **{sc['partial']:,} `partial` ({(sc['success']+sc['partial'])/summary['m1']['source_audit']['tex_verified']:.2%} parse được)** |
    | Tổng dòng 3 bảng M2 sau khử trùng | `elements`: **{m2s['rows']['elements']:,}** (-{m2s['deduplication']['elements']['reduction_rate']:.2%}); `hierarchy`: **{m2s['rows']['hierarchy']:,}**; `bibtex`: **{m2s['rows']['bibtex']:,}** (-{m2s['deduplication']['bibtex']['reduction_rate']:.2%}) |
    | Kiểm chuẩn cấu trúc 5 bảng toàn cục (`validate_project`) | **`structural_valid = True`** (`0` lỗi cấu trúc/khóa ngoại/chu trình) |
    | Benchmark Google Colab CPU-only (5 phiên cold) | **{bench_tot['total_profiler_sec']:,.2f} giây** (**{bench_tot['avg_sec_per_unique_publication']:.4f}s/bài**), Peak RSS **{bench_tot['max_session_peak_rss_mib']:.2f} MiB**, Output **{bench_tot['final_output_bytes']/1024**3:.2f} GiB** |

    ## Thành viên và dải ID phụ trách

    - **Nguyễn Quốc Đạt - 24120282** (`2412.18848 - 2501.02641`): discovery, metadata/version và tích hợp.
    - **Nguyễn Đình Tuấn - 24120237** (`2502.03235 - 2502.08234`): tải, giải nén, lọc nguồn và audit.
    - **Trần Nguyên Tân - 24120438** (`2407.12839 - 2407.17838`): references, Semantic Scholar và provenance.
    - **Dương Phan Minh Trí - 24120470** (`2406.17938 - 2407.02838`): lưu trữ, schema, parser, chuẩn hóa và `--resume` Colab CPU.
    - **Trịnh Vỹ Triết - 24120474** (`2406.12938 - 2406.17937`): runner, profiler, benchmark và dựng Book.

    ## Cấu trúc báo cáo

    - **[Milestone 1: Thu thập dữ liệu](chapters/00_m1_overview.ipynb)**: Discovery, tải & kiểm toán nguồn, Semantic Scholar references, mô hình 5 bảng và đo crawler M1.
    - **[Milestone 2: Phân tích cấu trúc và chuẩn hóa](chapters/00_m2_overview.ipynb)**: Gathering đa tệp, dựng hierarchy, chuẩn hóa LaTeX/Toán, trích `.bib`/`.bbl`, khử trùng 2 tầng và benchmark chính thức 25.000 bài trên Google Colab CPU-only.
    - **[Thảo luận](chapters/12_discussion_and_conclusion.ipynb)** & các phụ lục: [Tái lập](chapters/09_reproducibility.ipynb), [Đối chiếu yêu cầu](chapters/10_requirements_and_limitations.ipynb), [Tài liệu tham khảo](chapters/11_references.md) và [QA giảng viên](chapters/13_teacher_qa.md).

    **URL Book cố định:** {BOOK_URL} | [Repository source]({SOURCE_REPO}/tree/main) | [Đề đồ án M2]({M2_STMT})
    """).strip() + "\n", encoding="utf-8")

    (output / "_toc.yml").write_text(dedent("""
    format: jb-book
    root: index
    parts:
      - caption: Milestone 1 - Thu thập dữ liệu
        chapters:
          - file: chapters/00_m1_overview
            sections:
              - file: chapters/01_discovery_and_versions
              - file: chapters/02_source_download_and_cleaning
              - file: chapters/03_reference_extraction
              - file: chapters/04_schema_and_data_quality
              - file: chapters/05_performance_benchmark
      - caption: Milestone 2 - Phân tích cấu trúc và chuẩn hóa
        chapters:
          - file: chapters/00_m2_overview
            sections:
              - file: chapters/06_parsing_and_hierarchy
              - file: chapters/07_standardization_and_deduplication
              - file: chapters/08_parser_benchmark
      - caption: Thảo luận và phụ lục
        chapters:
          - file: chapters/12_discussion_and_conclusion
          - file: chapters/09_reproducibility
          - file: chapters/10_requirements_and_limitations
          - file: chapters/11_references
          - file: chapters/13_teacher_qa
    """).strip() + "\n", encoding="utf-8")

    (output / "_config.yml").write_text(dedent(f"""
    title: arXiv Harvester - Milestone 1 và 2 (25.000 bài)
    author: Nhóm arXiv Harvester
    repository:
      url: {SOURCE_REPO}-book
      branch: main
    html:
      use_repository_button: true
      use_edit_page_button: true
      extra_css: [report.css]
    execute:
      execute_notebooks: force
      allow_errors: false
      timeout: 600
    sphinx:
      config:
        language: vi
        exclude_patterns: [_build, README.md, '**.ipynb_checkpoints']
        nb_execution_raise_on_error: true
        html_static_path: [_static]
    """).strip() + "\n", encoding="utf-8")

    (output / "_static/report.css").write_text(dedent("""
    .bd-article-container { max-width: 60rem; }
    .bd-article h1 { line-height: 1.25; }
    .bd-article p, .bd-article li { line-height: 1.7; }
    .dataframe { font-size: .88rem; }
    .dataframe th, .dataframe td { padding: .5rem .68rem; }
    .cell_output { margin: .8rem 0 1.6rem; }
    """).strip() + "\n", encoding="utf-8")

    (output / ".gitignore").write_text("_build/\n.jupyter_cache/\n__pycache__/\n.ipynb_checkpoints/\n", encoding="utf-8")
    (output / ".gitattributes").write_text("* -text\n", encoding="utf-8")
    (output / "requirements.txt").write_text(dedent(f"""
    jupyter-book==1.0.4.post1
    pandas==3.1.1
    pyarrow==26.0.1
    matplotlib==3.11.2
    nbformat==5.11.1
    arxiv-harvester @ git+{SOURCE_REPO}.git@main
    """).strip() + "\n", encoding="utf-8")

    (output / "README.md").write_text(dedent(f"""
    # Báo cáo Jupyter Book M1-M2 (25.000 bài báo)

    URL xuất bản cố định: {BOOK_URL}

    ```bash
    python -m pip install -r requirements.txt
    jupyter-book build . --all -W
    ```

    Mọi bảng thống kê và biểu đồ được notebook sinh trực tiếp từ `report_summary.json` và chạy code parser thật trên ví dụ minh họa khi biên dịch Jupyter Book; không chứa corpus gốc, ID bài báo cá nhân, file Parquet hay log/secret.
    """).strip() + "\n", encoding="utf-8")

    (output / ".github/workflows/pages.yml").write_text(dedent("""
    name: Build and deploy Jupyter Book
    on:
      push:
        branches: [main]
      workflow_dispatch:
    permissions:
      contents: read
      pages: write
      id-token: write
    concurrency:
      group: pages
      cancel-in-progress: false
    jobs:
      pages:
        runs-on: ubuntu-latest
        environment:
          name: github-pages
          url: ${{ steps.deployment.outputs.page_url }}
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: '3.12'
              cache: pip
          - run: python -m pip install -r requirements.txt
          - run: jupyter-book build . --all -W
            env:
              PYTHONPATH: ${{ github.workspace }}
          - uses: actions/configure-pages@v5
          - uses: actions/upload-pages-artifact@v4
            with:
              name: github-pages-${{ github.run_id }}-${{ github.run_attempt }}
              path: _build/html
          - name: Deploy
            id: deployment
            uses: actions/deploy-pages@v4
            with:
              artifact_name: github-pages-${{ github.run_id }}-${{ github.run_attempt }}
              timeout: 1200000
    """).strip() + "\n", encoding="utf-8")

    if do_build:
        jb_bin = Path(sys.executable).with_name("jupyter-book")
        subprocess.run([str(jb_bin), "build", str(output), "--all", "-W"], check=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("build/m2_workspace"))
    parser.add_argument("--output", type=Path, default=Path("build/m2_book_staging"))
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    out = write_book(args.workspace, args.output, do_build=args.build)
    print("BOOK_READY:", out)


if __name__ == "__main__":
    main()
