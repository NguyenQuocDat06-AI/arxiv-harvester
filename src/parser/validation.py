"""Check the five M1/M2 tables and report corpus coverage."""
from __future__ import annotations
import argparse
import importlib
import hashlib
import json
from pathlib import Path
import re
import pyarrow.parquet as pq
from .storage import validate_directory

_crawler = "src.crawler" if __package__.startswith("src.") else "crawler"
_sources = importlib.import_module(_crawler + ".validate_sources")
_write_json = importlib.import_module(_crawler + ".profiler")._write_json_atomic


def validate_project(course_dir: str, parsed_dir: str, publications: str) -> dict:
    course, parsed = Path(course_dir), Path(parsed_dir)
    m1 = _sources.validate_course_tables(str(course))
    paper_ids = set(pq.ParquetFile(course / "papers.parquet").read(columns=["arxiv_id"])["arxiv_id"].to_pylist())
    m2 = validate_directory(parsed, paper_ids)
    expected, source_statuses = set(), {}
    working_ids, unknown_version_papers = set(), set()
    for path in _sources.publication_files(publications):
        for paper in pq.ParquetFile(path).read(columns=["id", "versions"]).to_pylist():
            identifier = paper["id"]
            working_ids.add(identifier)
            if not paper.get("versions"):
                unknown_version_papers.add(identifier)
            for version in paper.get("versions") or []:
                tag = str(version.get("version") or "")
                if not re.fullmatch(r"v[1-9]\d*", tag):
                    raise ValueError(f"Invalid working version: {identifier}/{tag}")
                pair = (identifier, int(tag[1:]))
                expected.add(pair)
                source_statuses[pair] = version.get("source_status")
    manifest = json.loads((parsed / "manifest.json").read_text(encoding="utf-8"))
    stats = json.loads((parsed / "stats.json").read_text(encoding="utf-8"))
    errors = []
    if working_ids != paper_ids:
        errors.append("Working publications and course papers have different ID sets")
    if unknown_version_papers:
        errors.append("Working publications contain unknown version metadata")
    if stats.get("status") not in {"completed", "completed_with_errors"}:
        errors.append("Latest parser run is not finished")
    if stats.get("versions") != len(manifest):
        errors.append("Manifest version count does not match parser stats")
    recorded, duplicate_pairs = set(), set()
    for row in manifest:
        pair = (row.get("arxiv_id"), row.get("version"))
        if pair in recorded:
            duplicate_pairs.add(pair)
        recorded.add(pair)
        if pair not in expected:
            errors.append("Manifest contains publication/version outside working M1 input")
        if row.get("status") == "empty_no_tex" and source_statuses.get(pair) not in {"pdf_only", "no_latex"}:
            errors.append("Empty parser version is not confirmed empty by M1 metadata")
    if duplicate_pairs:
        errors.append("Duplicate publication/version in parser manifest")
    dedup = stats.get("deduplication", {})
    for name in ("elements", "bibtex"):
        if dedup.get(name, {}).get("after") != m2["rows"][name]:
            errors.append(f"{name} store size does not match parser statistics")
    structural_valid = m1["valid"] and m2["valid"] and not errors
    missing = expected - recorded
    full = (structural_valid and not missing and bool(expected)
            and all(row.get("status") in {"success", "empty_no_tex"} for row in manifest))
    return {"scope": "Five-table structure and version coverage; source audit, benchmarks and submission are separate.",
            "inputs": {"parser_run_id": stats.get("run_id"), "parser_code_hash": stats.get("code_hash"),
                       "manifest_sha256": hashlib.sha256((parsed / "manifest.json").read_bytes()).hexdigest()},
            "structural_valid": structural_valid, "processing_complete": full,
            "errors": sorted(set([*errors, *m1["errors"], *m2["errors"]])), "m1": m1, "m2": m2,
            "coverage": {"expected_versions": len(expected), "recorded_versions": len(recorded & expected),
                         "fraction": len(recorded & expected) / len(expected) if expected else None,
                         "missing_versions": len(missing), "missing_sample": sorted(missing)[:20],
                         "partial_versions": sum(row.get("status") == "partial" for row in manifest),
                         "error_versions": sum(str(row.get("status", "")).startswith("error") for row in manifest)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-dir", required=True)
    parser.add_argument("--parsed-dir", required=True)
    parser.add_argument("--publications", required=True, help="Full working M1 publication table or directory of shards")
    parser.add_argument("--output", required=True, help="Write a JSON validation report")
    parser.add_argument("--require-full", action="store_true", help="Return exit code 2 when coverage/status is incomplete")
    args = parser.parse_args(argv)
    result = validate_project(args.course_dir, args.parsed_dir, args.publications)
    _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=True))
    if not result["structural_valid"]:
        raise SystemExit(1)
    if args.require_full and not result["processing_complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
