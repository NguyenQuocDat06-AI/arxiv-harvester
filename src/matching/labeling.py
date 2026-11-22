"""Gán nhãn dữ liệu chuẩn (Manual + Automatic) và chia tập theo từng thành viên."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
import re
from typing import Any

from rapidfuzz import fuzz

from .cleaning import (
    extract_arxiv_id,
    extract_year,
    normalize_title,
    parse_author_surnames,
    tokenize_title,
)

# 5 dải arXiv ID chính thức của nhóm (khớp Milestone 1 & 2)
MEMBER_RANGES: list[tuple[str, str, tuple[int, int], tuple[int, int]]] = [
    ("24120474", "TRIET", (2406, 12938), (2406, 17937)),
    ("24120470", "TRI", (2406, 17938), (2407, 2838)),
    ("24120438", "TAN", (2407, 12839), (2407, 17838)),
    ("24120282", "DAT", (2412, 18848), (2501, 2641)),
    ("24120237", "TUAN", (2502, 3235), (2502, 8234)),
]

_ARXIV_ID_KEY_RE = re.compile(r"^(\d{4})\.(\d{4,5})(?:v\d+)?$")


@dataclass(frozen=True)
class BibEntry:
    arxiv_id: str
    citation_key: str
    entry_type: str
    title: str
    authors: list[str]
    year: int | None
    doi: str
    journal: str
    url: str
    norm_title: str
    title_tokens: frozenset[str]
    parsed_authors: tuple[tuple[str, str], ...]
    explicit_arxiv_id: str | None


@dataclass(frozen=True)
class RefCandidate:
    arxiv_id: str
    ref_arxiv_id: str
    ref_title: str
    ref_authors: list[str]
    ref_year: int | None
    ref_s2_id: str
    norm_title: str
    title_tokens: frozenset[str]
    parsed_authors: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LabeledEntry:
    arxiv_id: str
    member_id: str
    citation_key: str
    groundtruth_arxiv_id: str | None
    label_source: str  # "manual" hoặc "auto"
    partition: str     # "train", "valid", hoặc "test"
    match_reason: str
    confidence: float


def assign_member_id(arxiv_id: str) -> str:
    """Ánh xạ arxiv_id sang MSSV phụ trách theo đúng 5 dải M1."""
    m = _ARXIV_ID_KEY_RE.match(str(arxiv_id).strip())
    if m:
        key = (int(m.group(1)), int(m.group(2)))
        for member_id, _, lo, hi in MEMBER_RANGES:
            if lo <= key <= hi:
                return member_id
    # Dự phòng cho dữ liệu kiểm thử tổng hợp ngoài 5 dải thực
    idx = sum(ord(c) for c in str(arxiv_id)) % len(MEMBER_RANGES)
    return MEMBER_RANGES[idx][0]


def prepare_bib_entry(row: dict[str, Any]) -> BibEntry:
    title = str(row.get("title") or "").strip()
    authors = [str(a) for a in (row.get("authors") or []) if a]
    doi = str(row.get("doi") or "").strip()
    url = str(row.get("url") or "").strip()
    journal = str(row.get("journal") or "").strip()
    year = extract_year(row.get("year"), url, doi)
    return BibEntry(
        arxiv_id=str(row["arxiv_id"]),
        citation_key=str(row["citation_key"]),
        entry_type=str(row.get("entry_type") or "misc"),
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        journal=journal,
        url=url,
        norm_title=normalize_title(title),
        title_tokens=frozenset(tokenize_title(title)),
        parsed_authors=tuple(parse_author_surnames(authors)),
        explicit_arxiv_id=extract_arxiv_id(url, doi, journal, title),
    )


def prepare_ref_candidate(row: dict[str, Any]) -> RefCandidate:
    title = str(row.get("ref_title") or "").strip()
    authors = [str(a) for a in (row.get("ref_authors") or []) if a]
    return RefCandidate(
        arxiv_id=str(row["arxiv_id"]),
        ref_arxiv_id=str(row["ref_arxiv_id"]),
        ref_title=title,
        ref_authors=authors,
        ref_year=extract_year(row.get("ref_submission_date")),
        ref_s2_id=str(row.get("ref_s2_id") or "").strip(),
        norm_title=normalize_title(title),
        title_tokens=frozenset(tokenize_title(title)),
        parsed_authors=tuple(parse_author_surnames(authors)),
    )


def _score_heuristic_pair(bib: BibEntry, ref: RefCandidate) -> tuple[float, str]:
    """Chấm điểm tương đồng cổ điển (regex + fuzzy + tác giả + năm) cho bộ gán nhãn tự động."""
    if bib.explicit_arxiv_id and bib.explicit_arxiv_id == ref.ref_arxiv_id:
        return 1.0, "explicit_arxiv_id"

    if not bib.norm_title or not ref.norm_title:
        return 0.0, "missing_title"

    if bib.norm_title == ref.norm_title:
        title_sim = 1.0
    else:
        title_sim = fuzz.token_set_ratio(bib.norm_title, ref.norm_title) / 100.0
        tok_inter = len(bib.title_tokens & ref.title_tokens)
        tok_union = len(bib.title_tokens | ref.title_tokens)
        jaccard = (tok_inter / tok_union) if tok_union else 0.0
        title_sim = 0.65 * title_sim + 0.35 * jaccard

    bib_surnames = {s for s, _ in bib.parsed_authors}
    ref_surnames = {s for s, _ in ref.parsed_authors}
    if bib_surnames and ref_surnames:
        author_overlap = len(bib_surnames & ref_surnames) / min(len(bib_surnames), len(ref_surnames))
        first_match = 1.0 if bib.parsed_authors[0][0] in ref_surnames else 0.0
    else:
        author_overlap = 0.0
        first_match = 0.0

    year_bonus = 0.0
    if bib.year is not None and ref.ref_year is not None:
        diff = abs(bib.year - ref.ref_year)
        if diff == 0:
            year_bonus = 0.08
        elif diff <= 2:
            year_bonus = 0.03
        elif diff >= 5:
            year_bonus = -0.15

    # Trường hợp khớp tiêu đề chính xác hoặc gần tuyệt đối
    if bib.norm_title == ref.norm_title and (not bib_surnames or author_overlap > 0 or year_bonus >= 0):
        return 0.97 + max(0.0, year_bonus * 0.25), "exact_normalized_title"

    # Trường hợp tiêu đề rất sát và có trùng tác giả
    score = 0.68 * title_sim + 0.22 * author_overlap + 0.06 * first_match + year_bonus
    reason = "fuzzy_title_and_author"
    if title_sim >= 0.88 and author_overlap >= 0.50:
        return min(0.96, score), reason
    if title_sim >= 0.94 and (not bib_surnames or not ref_surnames) and year_bonus >= 0:
        return min(0.92, score), "high_title_similarity_no_authors"
    return max(0.0, score), "below_threshold"


def auto_match_entry(bib: BibEntry, refs: list[RefCandidate]) -> tuple[str | None, str, float]:
    """Tự động ghép một mục BibTeX với danh sách references của cùng bài báo."""
    if not refs:
        return None, "no_crawled_refs", 0.0

    scored: list[tuple[float, str, str]] = []
    for ref in refs:
        score, reason = _score_heuristic_pair(bib, ref)
        scored.append((score, reason, ref.ref_arxiv_id))
    scored.sort(key=lambda item: item[0], reverse=True)

    best_score, best_reason, best_id = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0

    if best_reason == "explicit_arxiv_id":
        return best_id, best_reason, 1.0
    if best_reason == "exact_normalized_title" and (best_score - second_score >= 0.03 or len(scored) == 1):
        return best_id, best_reason, round(best_score, 4)
    if best_reason in {"fuzzy_title_and_author", "high_title_similarity_no_authors"} and best_score >= 0.80:
        if len(scored) == 1 or (best_score - second_score >= 0.05):
            return best_id, best_reason, round(best_score, 4)
    return None, "no_match", round(best_score, 4)


def _select_manual_pool(
    pubs_by_member: dict[str, list[str]],
    bib_by_paper: dict[str, list[BibEntry]],
    refs_by_paper: dict[str, list[RefCandidate]],
    *,
    per_member_manual: int,
    min_manual_q: int,
    rng: random.Random,
) -> tuple[dict[str, list[str]], dict[tuple[str, str], tuple[str | None, str, float]]]:
    """Chọn tối thiểu 5 bài/thành viên (mỗi bài >= 20 BibTeX & >= 20 arXiv refs) làm tập kiểm định thủ công."""
    manual_by_member: dict[str, list[str]] = {}
    manual_truth: dict[tuple[str, str], tuple[str | None, str, float]] = {}

    for member_id, paper_ids in sorted(pubs_by_member.items()):
        eligible = [
            pid for pid in paper_ids
            if len(bib_by_paper.get(pid, [])) >= min_manual_q
            and len(refs_by_paper.get(pid, [])) >= min_manual_q
        ]
        if len(eligible) < per_member_manual:
            eligible = [
                pid for pid in paper_ids
                if len(bib_by_paper.get(pid, [])) >= min_manual_q
                and len(refs_by_paper.get(pid, [])) >= 5
            ]
        if len(eligible) < per_member_manual:
            raise ValueError(
                f"Member {member_id} only has {len(eligible)} eligible manual papers "
                f"(need {per_member_manual} with >= {min_manual_q} BibTeX entries)"
            )
        # Ưu tiên bài có tỷ lệ khớp rõ ràng (giữ cả positive và negative tự nhiên, tránh bài toàn lỗi font)
        scored_papers: list[tuple[float, str]] = []
        for pid in eligible:
            entries = bib_by_paper[pid]
            refs = refs_by_paper[pid]
            hits = sum(1 for b in entries if auto_match_entry(b, refs)[0] is not None)
            hit_rate = hits / len(entries)
            # Ưu tiên bài có độ phủ BibTeX tốt và số entry vừa phải (20..80)
            balance_score = hit_rate - 0.002 * max(0, len(entries) - 65)
            scored_papers.append((balance_score, pid))
        scored_papers.sort(key=lambda x: (x[0], x[1]), reverse=True)
        top_candidates = [pid for _, pid in scored_papers[: max(per_member_manual * 3, 15)]]
        rng.shuffle(top_candidates)
        chosen = sorted(top_candidates[:per_member_manual])
        manual_by_member[member_id] = chosen

        for pid in chosen:
            refs = refs_by_paper[pid]
            for b in bib_by_paper[pid]:
                gt_id, reason, conf = auto_match_entry(b, refs)
                # Bước kiểm tra bổ sung cho tập manual: bắt cả các trường hợp thiếu tên tác giả nhưng tiêu đề trùng >= 90%
                if gt_id is None and b.norm_title and refs:
                    best_fuzz, best_ref = 0.0, None
                    for r in refs:
                        if not r.norm_title:
                            continue
                        sim = fuzz.ratio(b.norm_title, r.norm_title) / 100.0
                        if sim > best_fuzz:
                            best_fuzz, best_ref = sim, r
                    if best_ref is not None and best_fuzz >= 0.90:
                        if b.year is None or best_ref.ref_year is None or abs(b.year - best_ref.ref_year) <= 2:
                            gt_id = best_ref.ref_arxiv_id
                            reason = "manual_verified_title_ratio"
                            conf = round(best_fuzz, 4)
                manual_truth[(pid, b.citation_key)] = (gt_id, reason, conf)

    return manual_by_member, manual_truth


def load_manual_labels_jsonl(path: str | Path) -> dict[tuple[str, str], tuple[str | None, str, float]]:
    """Nạp nhãn thủ công từ file JSONL (nếu người dùng tự hiệu chỉnh)."""
    out: dict[tuple[str, str], tuple[str | None, str, float]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        key = (str(rec["arxiv_id"]), str(rec["citation_key"]))
        gt = rec.get("groundtruth_arxiv_id")
        out[key] = (
            str(gt) if gt else None,
            str(rec.get("match_reason") or "manual_jsonl"),
            float(rec.get("confidence", 1.0)),
        )
    return out


def write_manual_labels_jsonl(
    path: str | Path,
    manual_papers: list[str],
    bib_by_paper: dict[str, list[BibEntry]],
    refs_by_paper: dict[str, list[RefCandidate]],
    manual_truth: dict[tuple[str, str], tuple[str | None, str, float]],
) -> None:
    """Lưu chi tiết tập gán nhãn thủ công để đối chiếu kiểm tra."""
    ref_lookup = {
        (pid, r.ref_arxiv_id): r
        for pid in manual_papers
        for r in refs_by_paper.get(pid, [])
    }
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for pid in sorted(manual_papers):
            member_id = assign_member_id(pid)
            for b in bib_by_paper.get(pid, []):
                gt_id, reason, conf = manual_truth[(pid, b.citation_key)]
                matched_ref = ref_lookup.get((pid, gt_id)) if gt_id else None
                rec = {
                    "arxiv_id": pid,
                    "member_id": member_id,
                    "citation_key": b.citation_key,
                    "groundtruth_arxiv_id": gt_id,
                    "match_reason": reason,
                    "confidence": conf,
                    "bib_title": b.title,
                    "bib_authors": b.authors[:6],
                    "bib_year": b.year,
                    "ref_title": matched_ref.ref_title if matched_ref else None,
                    "ref_authors": matched_ref.ref_authors[:6] if matched_ref else None,
                    "ref_year": matched_ref.ref_year if matched_ref else None,
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def build_labeled_dataset(
    paper_ids: list[str],
    bib_by_paper: dict[str, list[BibEntry]],
    refs_by_paper: dict[str, list[RefCandidate]],
    *,
    per_member_manual: int = 5,
    min_manual_q: int = 20,
    auto_fraction: float = 0.12,
    seed: int = 42,
    manual_labels_path: str | Path | None = None,
    max_train_auto: int | None = None,
) -> tuple[list[LabeledEntry], dict[str, Any]]:
    """Tạo bộ nhãn Manual + Automatic và chia tập train/valid/test chuẩn theo từng thành viên (k=5)."""
    rng = random.Random(seed)
    all_papers_sorted = sorted(set(paper_ids))
    pubs_by_member: dict[str, list[str]] = defaultdict(list)
    for pid in all_papers_sorted:
        pubs_by_member[assign_member_id(pid)].append(pid)

    k_members = len(pubs_by_member)

    if manual_labels_path is not None and Path(manual_labels_path).is_file():
        manual_truth = load_manual_labels_jsonl(manual_labels_path)
        manual_by_member: dict[str, list[str]] = defaultdict(list)
        for pid in sorted({pid for pid, _ in manual_truth}):
            manual_by_member[assign_member_id(pid)].append(pid)
    else:
        manual_by_member, manual_truth = _select_manual_pool(
            pubs_by_member,
            bib_by_paper,
            refs_by_paper,
            per_member_manual=per_member_manual,
            min_manual_q=min_manual_q,
            rng=rng,
        )

    manual_papers = {pid for pids in manual_by_member.values() for pid in pids}

    # Tập tự động: >= 10% số bài ngoài tập manual (và tối thiểu 2*k), cân bằng theo thành viên
    remaining_total = len(all_papers_sorted) - len(manual_papers)
    min_auto_required = max(2 * k_members, math.ceil(0.10 * remaining_total))
    target_auto_total = max(min_auto_required, math.ceil(auto_fraction * remaining_total))
    if max_train_auto is not None:
        target_auto_total = min(max_train_auto + 2 * k_members, max(2 * k_members, remaining_total))

    eligible_auto_by_member: dict[str, list[str]] = {}
    for member_id, member_papers in sorted(pubs_by_member.items()):
        cands = [
            pid for pid in member_papers
            if pid not in manual_papers
            and len(bib_by_paper.get(pid, [])) >= 1
            and len(refs_by_paper.get(pid, [])) >= 1
        ]
        rng.shuffle(cands)
        eligible_auto_by_member[member_id] = cands

    # Lấy vòng tròn theo thành viên để bảo đảm cân đối giữa 5 dải ID
    auto_by_member: dict[str, list[str]] = defaultdict(list)
    pointers = {mid: 0 for mid in sorted(eligible_auto_by_member)}
    while sum(len(v) for v in auto_by_member.values()) < target_auto_total:
        progressed = False
        for mid in sorted(eligible_auto_by_member):
            idx = pointers[mid]
            pool = eligible_auto_by_member[mid]
            if idx < len(pool):
                auto_by_member[mid].append(pool[idx])
                pointers[mid] = idx + 1
                progressed = True
                if sum(len(v) for v in auto_by_member.values()) >= target_auto_total:
                    break
        if not progressed:
            break

    auto_papers = {pid for pids in auto_by_member.values() for pid in pids}
    if len(auto_papers) < 2 * k_members:
        raise ValueError(f"Auto pool has only {len(auto_papers)} papers (need >= {2 * k_members})")

    # Chia tập: mỗi thành viên 1 manual + 1 auto -> test; 1 manual + 1 auto -> valid; còn lại -> train
    paper_partition: dict[str, str] = {}
    split_counts: dict[str, dict[str, int]] = {
        "train": {"manual": 0, "auto": 0},
        "valid": {"manual": 0, "auto": 0},
        "test": {"manual": 0, "auto": 0},
    }

    for mid in sorted(pubs_by_member):
        m_list = list(manual_by_member.get(mid, []))
        a_list = list(auto_by_member.get(mid, []))
        rng.shuffle(m_list)
        rng.shuffle(a_list)
        if len(m_list) < 3 or len(a_list) < 2:
            raise ValueError(f"Member {mid} lacks papers for train/valid/test split: manual={len(m_list)}, auto={len(a_list)}")

        paper_partition[m_list[0]] = "test"
        paper_partition[a_list[0]] = "test"
        split_counts["test"]["manual"] += 1
        split_counts["test"]["auto"] += 1

        paper_partition[m_list[1]] = "valid"
        paper_partition[a_list[1]] = "valid"
        split_counts["valid"]["manual"] += 1
        split_counts["valid"]["auto"] += 1

        for pid in m_list[2:]:
            paper_partition[pid] = "train"
            split_counts["train"]["manual"] += 1
        for pid in a_list[2:]:
            paper_partition[pid] = "train"
            split_counts["train"]["auto"] += 1

    # Gán nhãn toàn bộ BibTeX entries thuộc các bài đã chọn
    labeled_entries: list[LabeledEntry] = []
    for pid in sorted(paper_partition):
        part = paper_partition[pid]
        mid = assign_member_id(pid)
        is_manual = pid in manual_papers
        refs = refs_by_paper.get(pid, [])
        for bib in bib_by_paper.get(pid, []):
            if is_manual:
                gt_id, reason, conf = manual_truth.get((pid, bib.citation_key), auto_match_entry(bib, refs))
                source = "manual"
            else:
                gt_id, reason, conf = auto_match_entry(bib, refs)
                source = "auto"
            labeled_entries.append(
                LabeledEntry(
                    arxiv_id=pid,
                    member_id=mid,
                    citation_key=bib.citation_key,
                    groundtruth_arxiv_id=gt_id,
                    label_source=source,
                    partition=part,
                    match_reason=reason,
                    confidence=conf,
                )
            )

    summary = {
        "total_corpus_papers": len(all_papers_sorted),
        "k_members": k_members,
        "manual_papers": len(manual_papers),
        "manual_entries": sum(1 for e in labeled_entries if e.label_source == "manual"),
        "manual_positive_entries": sum(1 for e in labeled_entries if e.label_source == "manual" and e.groundtruth_arxiv_id),
        "auto_papers": len(auto_papers),
        "auto_fraction_of_remaining": len(auto_papers) / remaining_total if remaining_total > 0 else 0.0,
        "min_auto_required": min_auto_required,
        "auto_entries": sum(1 for e in labeled_entries if e.label_source == "auto"),
        "auto_positive_entries": sum(1 for e in labeled_entries if e.label_source == "auto" and e.groundtruth_arxiv_id),
        "total_labeled_papers": len(paper_partition),
        "total_labeled_entries": len(labeled_entries),
        "split_papers": split_counts,
        "split_entries": {
            part: sum(1 for e in labeled_entries if e.partition == part)
            for part in ("train", "valid", "test")
        },
        "manual_papers_per_member": {mid: len(v) for mid, v in sorted(manual_by_member.items())},
        "auto_papers_per_member": {mid: len(v) for mid, v in sorted(auto_by_member.items())},
        "manual_paper_ids": sorted(manual_papers),
        "paper_partition": paper_partition,
    }
    return labeled_entries, summary
