"""Trích xuất 25 đặc trưng cổ điển cho từng cặp ứng viên (BibTeX entry, crawled arXiv reference)."""
from __future__ import annotations

from collections import defaultdict
import gc
import math
from pathlib import Path
import re
from typing import Any

import numpy as np
import pyarrow.parquet as pq
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer

from .cleaning import extract_citation_keys_from_tex, fold_ascii, normalize_title, strip_latex
from .labeling import BibEntry, LabeledEntry, RefCandidate

BASE_METADATA_FEATURES: tuple[str, ...] = (
    # Nhóm 1: Tương đồng tiêu đề (7 đặc trưng)
    "title_exact_norm",
    "title_token_jaccard",
    "title_token_dice",
    "title_containment_bib_in_ref",
    "title_rapidfuzz_ratio",
    "title_tfidf_cosine",
    "title_len_ratio",
    # Nhóm 2: Khớp tác giả (5 đặc trưng)
    "first_author_surname_match",
    "author_surname_jaccard",
    "author_surname_recall",
    "author_initial_surname_match",
    "author_count_diff",
    # Nhóm 3: Thời gian & định danh (5 đặc trưng)
    "arxiv_id_exact_match",
    "year_exact_match",
    "year_abs_diff",
    "year_diff_signed",
    "cite_key_author_year_hit",
)

POOL_RELATIVE_FEATURES: tuple[str, ...] = (
    # Nhóm 4: Tương đối trong tập ứng viên của cùng bài báo (4 đặc trưng)
    "title_tfidf_margin_to_best",
    "title_tfidf_rank_inv",
    "author_jaccard_margin_to_best",
    "pool_size_log",
)

HIERARCHY_CONTEXT_FEATURES: tuple[str, ...] = (
    # Nhóm 5: Ngữ cảnh từ cây cấu trúc Milestone 2 (elements + hierarchy) (4 đặc trưng)
    "hier_cite_count",
    "hier_in_intro_or_related",
    "hier_context_title_tfidf_cosine",
    "hier_context_author_hit",
)

FEATURE_NAMES: tuple[str, ...] = (
    *BASE_METADATA_FEATURES,
    *POOL_RELATIVE_FEATURES,
    *HIERARCHY_CONTEXT_FEATURES,
)

PARTITION_TO_CODE: dict[str, int] = {"train": 0, "valid": 1, "test": 2}

_INTRO_OR_RELATED_RE = re.compile(
    r"\b(intro|introduction|related|background|literature|overview|prior|preliminaries|survey)\b",
    re.IGNORECASE,
)
_HEADING_KINDS = frozenset({"section", "subsection", "subsubsection", "chapter", "title", "heading"})


def _filter_per_paper_parquet_paths(paths: list[Path], target_papers: set[str]) -> list[Path]:
    """Khi dữ liệu M2 lưu mỗi bài 1 file (<arxiv_id_slug>.parquet), chỉ mở đúng file của tập mục tiêu."""
    if not paths or not target_papers:
        return paths
    target_stems = {pid.replace("/", "_").replace(".", "-") for pid in target_papers}
    matched = [p for p in paths if p.stem in target_stems]
    # Chỉ rút gọn khi khớp rõ rệt kiểu đặt tên theo bài; nếu là shard chung (part-0.parquet) thì giữ nguyên
    if matched and len(matched) >= min(len(target_stems), max(1, int(0.5 * len(target_stems)))):
        return matched
    return paths


def load_m2_citation_context(
    parsed_dir: str | Path,
    target_papers: set[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Đọc phân luồng (streaming) M2 elements + hierarchy chỉ cho tập bài được gán nhãn."""
    root = Path(parsed_dir)
    all_elem_paths = sorted((root / "elements").glob("*.parquet"))
    all_hier_paths = sorted((root / "hierarchy").glob("*.parquet"))
    if not all_elem_paths or not all_hier_paths or not target_papers:
        return {}

    elem_paths = _filter_per_paper_parquet_paths(all_elem_paths, target_papers)
    hier_paths = _filter_per_paper_parquet_paths(all_hier_paths, target_papers)

    headings_by_paper: dict[str, dict[str, str]] = defaultdict(dict)
    citing_elements: dict[str, list[tuple[str, list[str], str]]] = defaultdict(list)

    for ep in elem_paths:
        pf = pq.ParquetFile(ep)
        for batch in pf.iter_batches(batch_size=8192, columns=["element_id", "arxiv_id", "kind", "content"]):
            col_id = batch.column("element_id").to_pylist()
            col_paper = batch.column("arxiv_id").to_pylist()
            col_kind = batch.column("kind").to_pylist()
            col_content = batch.column("content").to_pylist()
            for eid, pid, kind, content in zip(col_id, col_paper, col_kind, col_content):
                if pid not in target_papers or not content:
                    continue
                k_str = str(kind or "")
                if k_str in _HEADING_KINDS:
                    headings_by_paper[pid][eid] = str(content)
                if "\\cite" in content:
                    keys = extract_citation_keys_from_tex(content)
                    if keys:
                        clean_ctx = strip_latex(content)[:280]
                        citing_elements[pid].append((eid, keys, clean_ctx))

    parent_map_by_paper: dict[str, dict[str, str]] = defaultdict(dict)
    for hp in hier_paths:
        pf = pq.ParquetFile(hp)
        for batch in pf.iter_batches(batch_size=16384, columns=["arxiv_id", "element_id", "parent_id"]):
            col_paper = batch.column("arxiv_id").to_pylist()
            col_child = batch.column("element_id").to_pylist()
            col_parent = batch.column("parent_id").to_pylist()
            for pid, cid, par_id in zip(col_paper, col_child, col_parent):
                if pid in target_papers and cid not in parent_map_by_paper[pid]:
                    parent_map_by_paper[pid][cid] = par_id

    context_map: dict[tuple[str, str], dict[str, Any]] = {}
    for pid, items in citing_elements.items():
        pmap = parent_map_by_paper.get(pid, {})
        hmap = headings_by_paper.get(pid, {})
        per_key_snippets: dict[str, list[str]] = defaultdict(list)
        per_key_intro: dict[str, float] = defaultdict(float)
        per_key_count: dict[str, int] = defaultdict(int)

        for eid, keys, clean_ctx in items:
            in_intro = 0.0
            cur = eid
            for _ in range(12):
                par = pmap.get(cur)
                if not par or par == cur:
                    break
                heading_txt = hmap.get(par)
                if heading_txt and _INTRO_OR_RELATED_RE.search(heading_txt):
                    in_intro = 1.0
                    break
                cur = par
            for key in keys:
                per_key_count[key] += 1
                if in_intro > per_key_intro[key]:
                    per_key_intro[key] = in_intro
                if len(per_key_snippets[key]) < 3 and clean_ctx:
                    per_key_snippets[key].append(clean_ctx)

        for key, cnt in per_key_count.items():
            ctx_text = " ".join(per_key_snippets.get(key, []))
            context_map[(pid, key)] = {
                "count": cnt,
                "in_intro_or_related": per_key_intro.get(key, 0.0),
                "context_norm": normalize_title(ctx_text),
            }

    del headings_by_paper, citing_elements, parent_map_by_paper
    gc.collect()
    return context_map


def fit_title_tfidf(
    labeled_entries: list[LabeledEntry],
    bib_by_paper: dict[str, list[BibEntry]],
    refs_by_paper: dict[str, list[RefCandidate]],
) -> TfidfVectorizer:
    """Huấn luyện bộ TF-IDF hoàn toàn trên tập TRAIN để tránh rò rỉ dữ liệu."""
    train_papers = {e.arxiv_id for e in labeled_entries if e.partition == "train"}
    if not train_papers:
        train_papers = {e.arxiv_id for e in labeled_entries}

    corpus: list[str] = []
    for pid in sorted(train_papers):
        for b in bib_by_paper.get(pid, []):
            if b.norm_title:
                corpus.append(b.norm_title)
        for r in refs_by_paper.get(pid, []):
            if r.norm_title:
                corpus.append(r.norm_title)

    if not corpus:
        corpus = ["arxiv paper placeholder"]

    vec = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=2 if len(corpus) > 500 else 1,
        max_features=40000,
        sublinear_tf=True,
    )
    vec.fit(corpus)
    return vec


def _cite_key_author_year_hit(cite_key: str, ref: RefCandidate) -> float:
    ck = fold_ascii(cite_key)
    hit = 0.0
    if ref.parsed_authors:
        first_surname = ref.parsed_authors[0][0]
        if len(first_surname) >= 3 and first_surname in ck:
            hit += 0.6
    if ref.ref_year is not None:
        yr = str(ref.ref_year)
        if yr in ck or yr[-2:] in ck:
            hit += 0.4
    return min(1.0, hit)


def build_candidate_features(
    labeled_entries: list[LabeledEntry],
    bib_by_paper: dict[str, list[BibEntry]],
    refs_by_paper: dict[str, list[RefCandidate]],
    *,
    tfidf: TfidfVectorizer,
    hierarchy_context: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tạo ma trận đặc trưng X gọn nhẹ (lưu query_meta riêng thay vì lặp chuỗi theo từng cặp)."""
    hierarchy_context = hierarchy_context or {}
    bib_lookup = {
        (b.arxiv_id, b.citation_key): b
        for pid in {e.arxiv_id for e in labeled_entries}
        for b in bib_by_paper.get(pid, [])
    }

    entries_by_paper: dict[str, list[LabeledEntry]] = defaultdict(list)
    for e in labeled_entries:
        entries_by_paper[e.arxiv_id].append(e)

    # Ước lượng trước tổng số dòng cặp để cấp phát 1 lần (tránh nhân đôi RAM khi vstack)
    total_pairs = 0
    for pid, p_entries in entries_by_paper.items():
        n_refs = len(refs_by_paper.get(pid, []))
        if n_refs > 0:
            total_pairs += len(p_entries) * n_refs

    n_feat = len(FEATURE_NAMES)
    X = np.zeros((total_pairs, n_feat), dtype=np.float32)
    y = np.zeros(total_pairs, dtype=np.int8)
    query_ids = np.zeros(total_pairs, dtype=np.int32)
    part_codes = np.zeros(total_pairs, dtype=np.int8)
    cand_ref_ids: list[str] = [""] * total_pairs

    # Lưu metadata mỗi query đúng 1 lần (tiết kiệm hàng GB RAM)
    query_meta: list[tuple[str, str, str, str, str | None]] = []
    empty_pool_entries: list[LabeledEntry] = []

    cursor = 0
    query_id = 0
    for pid in sorted(entries_by_paper):
        p_entries = entries_by_paper[pid]
        refs = refs_by_paper.get(pid, [])
        if not refs:
            empty_pool_entries.extend(p_entries)
            continue

        n_refs = len(refs)
        ref_mat = tfidf.transform([r.norm_title for r in refs])
        pool_log = math.log1p(n_refs)

        # Tiền tính tập từ và tác giả của references 1 lần cho cả bài
        ref_toks_list = [r.title_tokens for r in refs]
        ref_surnames_list = [{s for s, _ in r.parsed_authors} for r in refs]
        ref_pairs_list = [set(r.parsed_authors) for r in refs]
        ref_first_list = [r.parsed_authors[0][0] if r.parsed_authors else "" for r in refs]
        ref_len_list = [len(r.norm_title) for r in refs]

        bib_objs = [bib_lookup[(pid, e.citation_key)] for e in p_entries]
        bib_mat = tfidf.transform([b.norm_title for b in bib_objs])
        sim_matrix = (bib_mat @ ref_mat.T).toarray()

        ctx_texts = [
            hierarchy_context.get((pid, e.citation_key), {}).get("context_norm", "")
            for e in p_entries
        ]
        ctx_mat = tfidf.transform(ctx_texts)
        ctx_sim_matrix = (ctx_mat @ ref_mat.T).toarray()

        for row_idx, (entry, bib) in enumerate(zip(p_entries, bib_objs)):
            block = X[cursor : cursor + n_refs]
            tfidf_scores = sim_matrix[row_idx]
            ctx_scores = ctx_sim_matrix[row_idx]
            best_tfidf = float(np.max(tfidf_scores))
            order = np.argsort(-tfidf_scores, kind="mergesort")
            ranks = np.empty(n_refs, dtype=np.float32)
            ranks[order] = np.arange(1, n_refs + 1, dtype=np.float32)

            bib_surnames = {s for s, _ in bib.parsed_authors}
            bib_pairs = set(bib.parsed_authors)
            bib_first = bib.parsed_authors[0][0] if bib.parsed_authors else ""
            bib_toks = bib.title_tokens
            bib_len = len(bib.norm_title)

            hctx = hierarchy_context.get((pid, bib.citation_key))
            hier_cnt = math.log1p(hctx["count"]) if hctx else 0.0
            hier_intro = float(hctx["in_intro_or_related"]) if hctx else 0.0
            ctx_norm = hctx.get("context_norm", "") if hctx else ""

            author_jaccards = np.zeros(n_refs, dtype=np.float32)
            pcode = PARTITION_TO_CODE[entry.partition]
            gt_id = entry.groundtruth_arxiv_id

            for j, ref in enumerate(refs):
                ref_toks = ref_toks_list[j]
                inter_tok = len(bib_toks & ref_toks)
                union_tok = len(bib_toks | ref_toks)

                exact_norm = 1.0 if (bib_len and bib.norm_title == ref.norm_title) else 0.0
                tok_jaccard = (inter_tok / union_tok) if union_tok else 0.0
                tok_dice = (2.0 * inter_tok / (len(bib_toks) + len(ref_toks))) if (bib_toks or ref_toks) else 0.0
                containment = (inter_tok / len(bib_toks)) if bib_toks else 0.0
                # Chỉ gọi token_sort_ratio khi hai tiêu đề không rỗng (nhanh với RapidFuzz C++)
                rf_ratio = (fuzz.token_sort_ratio(bib.norm_title, ref.norm_title) / 100.0) if (bib_len and ref_len_list[j]) else 0.0
                tfidf_cos = float(tfidf_scores[j])
                len_ratio = (min(bib_len, ref_len_list[j]) / max(bib_len, ref_len_list[j])) if (bib_len and ref_len_list[j]) else 0.0

                ref_surnames = ref_surnames_list[j]
                ref_first = ref_first_list[j]
                first_match = 1.0 if (bib_first and ref_first and bib_first == ref_first) else 0.0
                a_inter = len(bib_surnames & ref_surnames)
                a_union = len(bib_surnames | ref_surnames)
                a_jacc = (a_inter / a_union) if a_union else 0.0
                author_jaccards[j] = a_jacc
                a_recall = (a_inter / len(bib_surnames)) if bib_surnames else 0.0
                pair_match = (len(bib_pairs & ref_pairs_list[j]) / len(bib_pairs)) if bib_pairs else 0.0
                a_cnt_diff = float(abs(len(bib.parsed_authors) - len(ref.parsed_authors)))

                id_exact = 1.0 if (bib.explicit_arxiv_id and bib.explicit_arxiv_id == ref.ref_arxiv_id) else 0.0
                if bib.year is not None and ref.ref_year is not None:
                    y_diff_signed = float(bib.year - ref.ref_year)
                    y_abs = float(abs(y_diff_signed))
                    y_exact = 1.0 if y_abs == 0 else 0.0
                else:
                    y_diff_signed = 0.0
                    y_abs = 5.0
                    y_exact = 0.0
                ck_hit = _cite_key_author_year_hit(bib.citation_key, ref)
                ctx_author_hit = 1.0 if (ctx_norm and ref_first and len(ref_first) >= 3 and ref_first in ctx_norm) else 0.0

                block[j, 0] = exact_norm
                block[j, 1] = tok_jaccard
                block[j, 2] = tok_dice
                block[j, 3] = containment
                block[j, 4] = rf_ratio
                block[j, 5] = tfidf_cos
                block[j, 6] = len_ratio
                block[j, 7] = first_match
                block[j, 8] = a_jacc
                block[j, 9] = a_recall
                block[j, 10] = pair_match
                block[j, 11] = a_cnt_diff
                block[j, 12] = id_exact
                block[j, 13] = y_exact
                block[j, 14] = y_abs
                block[j, 15] = y_diff_signed
                block[j, 16] = ck_hit
                block[j, 17] = best_tfidf - tfidf_cos
                block[j, 18] = 1.0 / ranks[j]
                block[j, 20] = pool_log
                block[j, 21] = hier_cnt
                block[j, 22] = hier_intro
                block[j, 23] = float(ctx_scores[j])
                block[j, 24] = ctx_author_hit

                pos_idx = cursor + j
                y[pos_idx] = 1 if (gt_id and gt_id == ref.ref_arxiv_id) else 0
                query_ids[pos_idx] = query_id
                part_codes[pos_idx] = pcode
                cand_ref_ids[pos_idx] = ref.ref_arxiv_id

            best_aj = float(np.max(author_jaccards))
            block[:, 19] = best_aj - author_jaccards

            query_meta.append((
                entry.arxiv_id,
                entry.partition,
                entry.label_source,
                entry.citation_key,
                gt_id,
            ))
            cursor += n_refs
            query_id += 1

    return {
        "X": X,
        "y": y,
        "groups": query_ids,
        "part_codes": part_codes,
        "query_meta": query_meta,
        "cand_ref_ids": cand_ref_ids,
        "empty_pool_entries": empty_pool_entries,
        "feature_names": list(FEATURE_NAMES),
    }
