"""Summarize saved parsing counts, deduplication and resource usage."""
from __future__ import annotations
from collections import Counter, defaultdict


def summarize(manifests: list[dict], papers: list[dict]) -> dict:
    status = Counter(row["status"] for row in manifests)
    available = sum(row.get("has_tex", False) for row in manifests)
    success = status["success"]
    coverage = []
    by_paper = defaultdict(list)
    for row in manifests:
        by_paper[row["arxiv_id"]].append(row)
    for paper in papers:
        identifier = paper.get("id") or paper.get("arxiv_id")
        rows = by_paper[identifier]
        counts = Counter(row["status"] for row in rows)
        expected = len(paper.get("versions") or [])
        parsed = counts["success"] + counts["partial"]
        known_versions = sum(row.get("version") is not None for row in rows)
        coverage.append({"arxiv_id": identifier, "expected_versions": expected,
                         "recorded_versions": len(rows), "statuses": dict(counts),
                         "versions_with_tex": sum(bool(row.get("has_tex")) for row in rows),
                         "success_versions": counts["success"], "partial_versions": counts["partial"],
                         "empty_versions": counts["empty_no_tex"],
                         "error_versions": sum(value for key, value in counts.items() if key.startswith("error")),
                         "parsed_version_coverage": parsed / expected if expected else None,
                         "successful_version_coverage": counts["success"] / expected if expected else None,
                         "version_coverage": known_versions / expected if expected else None})
    def ratio(before, after):
        return (before - after) / before if before else None
    counts = {}
    for name in ("elements", "bibtex"):
        before = sum(row.get(name + "_before", 0) for row in manifests)
        # Count each publication's stored size once.
        after = sum(row.get(name + "_store_size", 0) for row in manifests)
        counts[name] = {"before": before, "after": after, "reduction_rate": ratio(before, after)}
    diagnostics = Counter(message for row in manifests for message in row.get("diagnostics", []))
    conflicts = sum(row.get("bibliography_conflicts", 0) for row in manifests)
    return {"publications": len(papers), "versions": len(manifests), "expected_versions": sum(len(p.get("versions") or []) for p in papers),
            "status_counts": dict(status),
            "versions_with_tex": available, "parsing_success_rate_on_tex": success / available if available else None,
            "unresolved_cites": sum(len(row.get("unresolved_cites", [])) for row in manifests),
            "diagnostics": [{"message": message, "versions": count} for message, count in diagnostics.most_common()],
            "bibliography_conflicts": conflicts,
            "versions_with_unmeasured_counts": sum(row.get("counts_measured") is False for row in manifests),
            "deduplication": counts, "publication_coverage": coverage}
