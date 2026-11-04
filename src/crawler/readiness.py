"""Inspect checkpoints and validate a finished crawl before continuing."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from .records import REFERENCE_TERMINAL
from .storage import PUBLICATIONS_SCHEMA, REFERENCES_SCHEMA
from .validate_sources import audit_sources, check_source_version, validate_course_tables
from .profiler import _write_json_atomic

PROTOCOL_VERSION = 1


def code_hash() -> str:
    return hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()


def runtime_info() -> dict:
    return {"protocol_version": PROTOCOL_VERSION, "checkpoint_schema": 2, "source_code_hash": code_hash(),
            "features": ["version_resume", "source_evidence", "reference_status", "existing_only", "shared_run_id",
                         "adaptive_s2", "source_retry_diagnostics", "s2_batch", "per_paper_checkpoint",
                         "persistent_cooldown", "http_diagnostics", "segmented_resume",
                         "source_pacing", "adaptive_ranges", "drive_batch_backup", "auto_rate_resume"]}


def checkpoint_plan(shard_dir: str | Path, raw_dir: str | Path, member_id: str, id_range: dict) -> dict:
    from .main import Checkpoint, _materialize

    checkpoint = Checkpoint(str(shard_dir))
    if not checkpoint.exists():
        return {"exists": False, "papers": 0, "pending_papers": [], "source_retry": [],
                "versions_reusable": 0, "references_needing_check": []}
    checkpoint.load(member_id, id_range, backup_legacy=False)
    pubs, _, observations = _materialize(checkpoint)
    pending, retry, refs, reusable = [], [], [], 0
    for identifier, paper in pubs.items():
        needs_source = not paper.get("versions")
        for version in paper.get("versions") or []:
            row = check_source_version(raw_dir, identifier, version)
            if row["verified"]:
                reusable += 1
            else:
                needs_source = True
                retry.append({key: row[key] for key in ("arxiv_id", "version", "source_status", "reason")})
        needs_refs = observations.get(identifier, {}).get("reference_status") not in REFERENCE_TERMINAL
        if needs_refs:
            refs.append(identifier)
        if needs_source or needs_refs:
            pending.append(identifier)
    return {"exists": True, "schema_version": checkpoint.state.get("schema_version", 1),
            "papers": len(pubs), "pending_papers": sorted(pending), "source_retry": retry,
            "versions_reusable": reusable, "references_needing_check": sorted(refs)}


def validate_run(shard_dir: str | Path, raw_dir: str | Path, export_dir: str | Path,
                 output_dir: str | Path, member_id: str, run_id: str, mode: str) -> dict:
    shard, raw, course, output = map(Path, (shard_dir, raw_dir, export_dir, output_dir))
    output.mkdir(parents=True, exist_ok=True)
    errors, warnings = [], []
    required = [shard / name for name in ("publications.parquet", "references.parquet", "crawl_status.parquet", "stats.json")]
    required += [course / name for name in ("papers.parquet", "references.parquet")]
    missing = [str(p) for p in required if not p.is_file()]
    result = {"validation_version": 2, "member_id": member_id, "run_id": run_id, "mode": mode,
              "source_code_hash": code_hash(), "checked_at": datetime.now(timezone.utc).isoformat(),
              "ready_for_full": False, "errors": errors, "warnings": warnings}
    if missing:
        errors.extend("Missing output: " + name for name in missing)
        _write_json_atomic(str(output / "validation.json"), result)
        return result
    publications = pq.ParquetFile(required[0]).read()
    references = pq.ParquetFile(required[1]).read()
    observations = pq.ParquetFile(required[2]).read().to_pylist()
    stats = json.loads(required[3].read_text(encoding="utf-8"))
    if stats.get("status") == "paused_rate_limit":
        result.update(paused_rate_limit=True, retry_after_sec=stats.get("retry_after_sec"), rate_limits=stats.get("rate_limits", {}))
    pubs, refs = publications.to_pylist(), references.to_pylist()
    ids = [row["id"] for row in pubs]
    if not publications.schema.equals(PUBLICATIONS_SCHEMA, check_metadata=False):
        errors.append("Working publications schema mismatch")
    if not references.schema.equals(REFERENCES_SCHEMA, check_metadata=False):
        errors.append("Working references schema mismatch")
    if not ids or len(set(ids)) != len(ids):
        errors.append("Missing or duplicate working paper IDs")
    if {r["arxiv_id"] for r in refs} - set(ids):
        errors.append("Working references contain orphan citing IDs")
    if stats.get("run_id") != run_id or stats.get("member_id") != member_id:
        errors.append("Stats belong to another run or member")
    if stats.get("source_code_hash") != code_hash():
        errors.append("Stats belong to another source version")
    if stats.get("is_mock") is not False or stats.get("status") != "completed":
        errors.append("Crawl did not complete successfully on real inputs")
    if (stats.get("results") or {}).get("failed", 0):
        errors.append("Crawl has pending failures")
    if any(not p.get("versions") for p in pubs):
        errors.append("Paper is missing version metadata")
    source_audit = audit_sources(str(required[0]), str(raw), str(output / "source_audit.parquet"))
    if source_audit["needs_verification_or_retry"]:
        errors.append("Some source versions need retry or evidence")
    by_id = {row["arxiv_id"]: row for row in observations}
    if len(by_id) != len(observations) or set(by_id) != set(ids):
        errors.append("Reference statuses do not cover working papers uniquely")
    statuses = Counter(row.get("reference_status", "unknown") for row in observations)
    if set(statuses) - REFERENCE_TERMINAL:
        errors.append("Reference requests remain unresolved")
    ref_counts = Counter(row["arxiv_id"] for row in refs)
    if any(row.get("reference_status") == "empty" and ref_counts[identifier]
           for identifier, row in by_id.items()):
        errors.append("Empty reference status conflicts with stored references")
    if statuses["not_indexed"] or statuses["bib_fallback"]:
        warnings.append("Some papers lack an indexed S2 result; preserve this coverage gap in reports")
    course_check = validate_course_tables(str(course))
    errors.extend(course_check["errors"])
    course_papers = pq.ParquetFile(course / "papers.parquet").read(columns=["arxiv_id"])["arxiv_id"].to_pylist()
    if set(course_papers) != set(ids):
        errors.append("Course paper IDs differ from working papers")
    course_refs = pq.ParquetFile(course / "references.parquet").read(columns=["arxiv_id", "ref_arxiv_id"]).to_pylist()
    if {(r["arxiv_id"], r["ref_arxiv_id"]) for r in course_refs} != {
        (r["arxiv_id"], r["ref_arxiv_id"]) for r in refs if r.get("ref_arxiv_id")
    }:
        errors.append("Course export lost or added reference edges")
    dates_missing = sum(v.get("created") is None for p in pubs for v in p.get("versions") or [])
    if dates_missing:
        warnings.append("Some revision dates remain unverified")
    result.update(ready_for_full=not errors, papers=len(pubs), working_references=len(refs),
                  course_export=course_check, source_audit=source_audit,
                  reference_statuses=dict(statuses), missing_version_dates=dates_missing,
                  input_hashes={str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in required})
    _write_json_atomic(str(output / "validation.json"), result)
    return result


def smoke_proof_valid(path: str | Path, member_id: str, expected_code_hash: str, minimum_papers: int = 1) -> bool:
    try:
        proof = json.loads(Path(path).read_text(encoding="utf-8"))
        if not (proof.get("validation_version") == 2 and proof.get("mode") == "smoke"
                and proof.get("ready_for_full") is True and proof.get("member_id") == member_id
                and proof.get("source_code_hash") == expected_code_hash and proof.get("input_hashes")
                and proof.get("papers", 0) >= minimum_papers):
            return False
        return all(Path(name).is_file() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
                   for name, digest in proof["input_hashes"].items())
    except (OSError, ValueError, TypeError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capabilities", action="store_true")
    args = parser.parse_args(argv)
    if args.capabilities:
        print(json.dumps(runtime_info()))
    else:
        parser.error("Specify --capabilities")


if __name__ == "__main__":
    main()
