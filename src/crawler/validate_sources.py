"""Audit local sources and prepare retry manifests."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import re
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from .records import base_id
from .source_downloader import ALLOWLIST_EXTENSIONS, get_dir_size_bytes
from .storage import _write_parquet_atomic
from .profiler import _write_json_atomic


def publication_files(path: str | Path) -> list[Path]:
    path = Path(path)
    return [path] if path.is_file() else sorted(p for p in path.rglob("publications.parquet")
                                               if "_checkpoint" not in p.parts and ".cache" not in p.parts)


def check_source_version(raw_dir: str | Path, identifier: str, version: dict) -> dict:
    raw = Path(raw_dir)
    tag = str(version.get("version") or "")
    if not re.fullmatch(r"v[1-9]\d*", tag):
        raise ValueError("Invalid version tag")
    directory = raw / "unzipped" / identifier.replace("/", "_") / tag
    if not directory.resolve().is_relative_to((raw / "unzipped").resolve()):
        raise ValueError("Source folder escapes corpus root")
    entries = list(directory.rglob("*")) if directory.is_dir() else []
    regular = [p for p in entries if p.is_file() and not p.is_symlink()]
    tex = [p for p in regular if p.suffix.lower() == ".tex"]
    unexpected = [p for p in entries if p.is_symlink() or (p.is_file() and p.suffix.lower() not in ALLOWLIST_EXTENSIONS)]
    actual_size = get_dir_size_bytes(directory) if directory.exists() else 0
    status = version.get("source_status")
    if status == "success":
        verified = bool(tex) and not unexpected and actual_size == version.get("size_after_bytes")
        reason = "tex_verified" if verified else "missing_tex_unexpected_files_or_size_mismatch"
    elif status in {"pdf_only", "no_latex"}:
        manifest = raw / "manifests" / (identifier.replace("/", "_") + tag + ".json")
        try:
            evidence = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            evidence = {}
        verified = (evidence.get("version_id") == identifier + tag and evidence.get("status") == status
                    and evidence.get("evidence") in {"pdf_header", "archive_without_tex"}
                    and not tex and not unexpected and actual_size == (version.get("size_after_bytes") or 0))
        reason = "empty_verified" if verified else "empty_unverified"
    else:
        verified, reason = False, "source_pending_or_failed"
    return {"arxiv_id": identifier, "version": tag, "source_status": status, "verified": verified,
            "reason": reason, "tex_files": len(tex), "bbl_files": sum(p.suffix.lower() == ".bbl" for p in regular),
            "files": len(regular), "actual_size_bytes": actual_size,
            "recorded_size_bytes": version.get("size_after_bytes"), "raw_dir": str(raw), "source_dir": str(directory)}


def audit_sources(publications: str, raw_dir: str, output: str) -> dict:
    files = publication_files(publications)
    if not files:
        raise FileNotFoundError("No publications.parquet found")
    rows, retry = [], []
    for source in files:
        member = source.parent.name
        raw = Path(raw_dir) / member if (Path(raw_dir) / member / "unzipped").exists() else Path(raw_dir)
        for paper in pq.ParquetFile(source).read().to_pylist():
            identifier = base_id(paper)
            for version in paper.get("versions") or []:
                row = {**check_source_version(raw, identifier, version), "member_id": member, "source_file": str(source)}
                rows.append(row)
                if not row["verified"]:
                    retry.append(row)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_parquet_atomic(pa.Table.from_pylist(rows), str(output_path))
    manifest = output_path.with_suffix(".retry.jsonl")
    with manifest.open("w", encoding="utf-8") as stream:
        for row in retry:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"version_count": len(rows), "verified": sum(row["verified"] for row in rows),
              "needs_verification_or_retry": len(retry), "reasons": dict(Counter(row["reason"] for row in rows)),
              "audit_file": str(output_path), "retry_manifest": str(manifest)}
    _write_json_atomic(str(output_path.with_suffix(".json")), report)
    return report


def validate_course_tables(directory: str) -> dict:
    from .storage import COURSE_PAPERS_SCHEMA, COURSE_REFERENCES_SCHEMA
    directory = Path(directory)
    paper_file = pq.ParquetFile(directory / "papers.parquet")
    reference_file = pq.ParquetFile(directory / "references.parquet")
    errors = []
    if not paper_file.schema_arrow.equals(COURSE_PAPERS_SCHEMA, check_metadata=False):
        errors.append("papers schema mismatch")
    if not reference_file.schema_arrow.equals(COURSE_REFERENCES_SCHEMA, check_metadata=False):
        errors.append("references schema mismatch")
    ids = paper_file.read(columns=["arxiv_id"])["arxiv_id"].to_pylist()
    refs = reference_file.read(columns=["arxiv_id", "ref_arxiv_id"])
    pairs = list(zip(refs["arxiv_id"].to_pylist(), refs["ref_arxiv_id"].to_pylist()))
    if any(not v for v in ids) or len(set(ids)) != len(ids):
        errors.append("missing/duplicate paper ID")
    if any(not a or not b for a, b in pairs) or len(set(pairs)) != len(pairs):
        errors.append("missing/duplicate reference key")
    if {a for a, _ in pairs} - set(ids):
        errors.append("orphan citing paper")
    return {"papers": len(ids), "references": len(pairs), "valid": not errors, "errors": errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publications", required=True, help="Parquet file or directory of shards")
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--output", required=True)
    print(json.dumps(audit_sources(**vars(parser.parse_args(argv))), ensure_ascii=True))


if __name__ == "__main__":
    main()
