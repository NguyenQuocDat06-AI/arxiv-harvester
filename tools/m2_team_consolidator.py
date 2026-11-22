"""Consolidate all 5 members' M1+M2 outputs into a globally validated 25,000-paper dataset."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any

_RUNNER_CANDIDATES = ["/content", "tools"]
if "__file__" in globals():
    _RUNNER_CANDIDATES.insert(0, str(Path(__file__).resolve().parent))
for _cand in _RUNNER_CANDIDATES:
    if (Path(_cand) / "m2_colab_runner.py").is_file() and _cand not in sys.path:
        sys.path.insert(0, _cand)

import m2_colab_runner as runner  # noqa: E402


def assert_colab_cpu_only() -> None:
    if "COLAB_RELEASE_TAG" not in os.environ:
        raise RuntimeError("Team 25,000 consolidation must run inside Google Colab (COLAB_RELEASE_TAG not set)")
    if Path("/dev/nvidia0").exists() or os.environ.get("COLAB_TPU_ADDR"):
        raise RuntimeError("Team 25,000 consolidation requires a CPU-only Colab runtime (GPU/TPU detected)")


def _safe_rel_path(name: str, allowed_roots: set[str], required_suffix: str | None = None) -> PurePosixPath:
    rel = PurePosixPath(name)
    if (
        not name
        or rel.is_absolute()
        or rel.as_posix() != name
        or ".." in rel.parts
        or "\\" in name
        or ":" in name
        or len(rel.parts) < 2
        or rel.parts[0] not in allowed_roots
    ):
        raise ValueError(f"Unsafe archive member path: {name!r}")
    if required_suffix is not None and rel.suffix != required_suffix:
        raise ValueError(f"Unexpected suffix for archive member: {name!r}")
    return rel


def ensure_member_m1_tables(
    member_cfg: dict[str, Any],
    member_drive_dir: Path,
    dest_shard_dir: Path,
) -> dict[str, str]:
    """Stage member's M1 Parquet tables (and stats.json) into dest_shard_dir.

    Prefers <member_drive_dir>/m1_tables/. Falls back to verifying and extracting
    shard/{publications,references,crawl_status}.parquet (+ stats.json) from the
    member's HEAD backup archive when fallback_head_archive_dir is configured.
    """
    dest_shard_dir.mkdir(parents=True, exist_ok=True)
    required = ("publications.parquet", "references.parquet", "crawl_status.parquet")
    optional = ("stats.json",)
    m1_dir = member_drive_dir / "m1_tables"

    if all((m1_dir / name).is_file() for name in required):
        digests: dict[str, str] = {}
        for name in (*required, *optional):
            src = m1_dir / name
            if src.is_file():
                digests[name] = runner.atomic_copy(src, dest_shard_dir / name)
        return digests

    fallback_raw = member_cfg.get("fallback_head_archive_dir")
    if not fallback_raw:
        raise FileNotFoundError(f"Missing M1 tables at {m1_dir} and no fallback_head_archive_dir configured")

    fallback_dir = Path(fallback_raw)
    gen = member_cfg["generation"]
    receipt_path = fallback_dir / f"{gen}.json"
    archive_path = fallback_dir / f"{gen}.tar.gz"
    if not receipt_path.is_file() or not archive_path.is_file():
        raise FileNotFoundError(f"Fallback HEAD receipt/archive missing in {fallback_dir} for generation {gen}")

    expected_head_sha = member_cfg.get("head_sha256")
    if expected_head_sha and runner.sha256_file(receipt_path) != expected_head_sha:
        raise ValueError(f"Fallback HEAD receipt SHA-256 mismatch for {member_cfg['member_id']}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if runner.sha256_file(archive_path) != receipt["archive_sha256"]:
        raise ValueError(f"Fallback HEAD archive SHA-256 mismatch for {member_cfg['member_id']}")

    allowed_targets = {f"shard/{name}": name for name in (*required, *optional)}
    extracted: dict[str, str] = {}
    with tarfile.open(archive_path, "r:gz") as tf:
        for member in tf.getmembers():
            if member.name not in allowed_targets:
                continue
            if not member.isfile():
                raise ValueError(f"Non-file member in fallback archive: {member.name}")
            _safe_rel_path(member.name, {"shard"})
            fname = allowed_targets[member.name]
            target = (dest_shard_dir / fname).resolve()
            if not target.is_relative_to(dest_shard_dir.resolve()):
                raise ValueError(f"Path traversal extracting {member.name}")
            with tf.extractfile(member) as src_f, target.open("wb") as out_f:
                shutil.copyfileobj(src_f, out_f)
            extracted[fname] = runner.sha256_file(target)

    missing_req = [name for name in required if name not in extracted]
    if missing_req:
        raise FileNotFoundError(
            f"Fallback HEAD archive {archive_path} missing required M1 outputs: {missing_req}"
        )

    # Best-effort cache into member_drive_dir/m1_tables so future runs avoid HEAD tar extraction.
    try:
        m1_dir.mkdir(parents=True, exist_ok=True)
        for fname in extracted:
            runner.atomic_copy(dest_shard_dir / fname, m1_dir / fname)
    except OSError:
        pass
    return extracted


def extract_member_m2_batches(member_full_dir: Path, parsed_out_dir: Path) -> dict[str, int]:
    """Verify and extract a member's M2 parquet batch archives into parsed_out_dir.

    Raises ValueError on checksum mismatch, unsafe member path, or filename collision
    with another member's extracted parquet shards.
    """
    batch_dir = member_full_dir / "output_batches"
    manifest_file = batch_dir / "batches_manifest.json"
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Missing M2 batches_manifest.json at {manifest_file}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    batches = manifest.get("batches") or []
    if not batches:
        raise ValueError(f"Empty output_batches list in {manifest_file}")

    parsed_resolved = parsed_out_dir.resolve()
    table_files = Counter()
    for batch in batches:
        tar_path = batch_dir / batch["batch_file"]
        if runner.sha256_file(tar_path) != batch["sha256"]:
            raise ValueError(f"Output batch checksum mismatch: {tar_path}")
        with tarfile.open(tar_path, "r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                rel = PurePosixPath(member.name)
                if len(rel.parts) != 2 or rel.parts[0] not in {"elements", "hierarchy", "bibtex"} or rel.suffix != ".parquet":
                    continue
                _safe_rel_path(member.name, {"elements", "hierarchy", "bibtex"}, ".parquet")
                dest = (parsed_out_dir / member.name).resolve()
                if not dest.is_relative_to(parsed_resolved):
                    raise ValueError(f"Path traversal in batch {tar_path}: {member.name}")
                if dest.exists():
                    raise ValueError(f"Colliding M2 parquet file across members: {member.name}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".parquet.tmp")
                try:
                    with tf.extractfile(member) as src_f, tmp.open("wb") as out_f:
                        shutil.copyfileobj(src_f, out_f)
                    os.replace(tmp, dest)
                finally:
                    tmp.unlink(missing_ok=True)
                table_files[rel.parts[0]] += 1
    return dict(table_files)


def consolidate_team(
    team_cfg: dict[str, Any],
    work_root: str | Path,
    drive_out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Merge M1 + M2 tables for all members, validate globally, and aggregate Colab benchmarks."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from src.crawler.benchmark_sessions import summarize_sessions
    from src.crawler.merge_shards import merge_all_shards
    from src.crawler.storage import export_to_course_spec
    from src.crawler.validate_sources import validate_course_tables
    from src.parser.statistics import summarize as summarize_m2
    from src.parser.validation import validate_project

    work_dir = Path(work_root).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    drive_root = Path(team_cfg["drive_output_root"])
    members = team_cfg.get("members") or []
    if not members:
        raise ValueError("team_cfg['members'] must be non-empty")

    m1_shards_dir = work_dir / "m1_shards"
    m1_merged_dir = work_dir / "m1_merged"
    course_dir = work_dir / "course_export"
    audit_dir = work_dir / "audit"
    parsed_dir = work_dir / "parsed"
    for d in (m1_shards_dir, m1_merged_dir, course_dir, audit_dir, parsed_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    # 1. Stage member M1 shards + extract M2 parquet batches
    extracted_counts: dict[str, dict[str, int]] = {}
    merged_manifest_rows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, int | None]] = set()
    member_stats_docs: list[dict[str, Any]] = []
    session_stats_paths: list[Path] = []
    audit_tables: list[pa.Table] = []

    for m in members:
        mid = m["member_id"]
        gen = m["generation"]
        member_drive_dir = Path(m.get("member_drive_dir") or (drive_root / "members" / mid / gen))
        member_full_dir = member_drive_dir / "full"

        ensure_member_m1_tables(m, member_drive_dir, m1_shards_dir / mid)
        extracted_counts[mid] = extract_member_m2_batches(member_full_dir, parsed_dir)

        mf_path = member_full_dir / "manifest.json"
        st_path = member_full_dir / "stats.json"
        val_path = member_full_dir / "project_validation.json"
        for required_json in (mf_path, st_path, val_path):
            if not required_json.is_file():
                raise FileNotFoundError(f"Missing M2 deliverable {required_json} for {mid}")

        member_val = json.loads(val_path.read_text(encoding="utf-8"))
        if not member_val.get("structural_valid"):
            raise ValueError(f"Member {mid} M2 output failed structural validation: {member_val.get('errors')}")

        member_mf = json.loads(mf_path.read_text(encoding="utf-8"))
        for row in member_mf:
            pair = (row.get("arxiv_id"), row.get("version"))
            if pair in seen_pairs:
                raise ValueError(f"Duplicate M2 manifest entry across members: {pair}")
            seen_pairs.add(pair)
            merged_manifest_rows.append(row)

        member_stats = json.loads(st_path.read_text(encoding="utf-8"))
        member_stats_docs.append({"member_id": mid, "short_name": m.get("short_name"), "stats": member_stats})

        run_stats = sorted((member_full_dir / "runs").glob("*/stats.json"))
        session_stats_paths.extend(run_stats if run_stats else [st_path])

        audit_src = Path(m.get("source_audit_parquet") or (member_drive_dir / "audit/source_audit.parquet"))
        if audit_src.is_file():
            audit_tables.append(pq.read_table(audit_src))

    # 2. Merge M1 shards + course export
    m1_overall_stats = merge_all_shards(
        shards_dir=str(m1_shards_dir),
        output_dir=str(m1_merged_dir),
        allow_mock=False,
        skip_corrupted=False,
        allow_missing_stats=True,
    )
    export_to_course_spec(str(m1_merged_dir), str(course_dir))
    course_check = validate_course_tables(str(course_dir))
    if not course_check["valid"]:
        raise RuntimeError(f"Consolidated course export invalid: {course_check}")

    merged_pubs = pq.read_table(m1_merged_dir / "publications.parquet").to_pylist()
    merged_refs = pq.read_table(m1_merged_dir / "references.parquet").to_pylist()

    # 3. Merge Source Audit
    source_audit_summary: dict[str, Any] = {
        "audit_tables_merged": len(audit_tables),
        "version_count": 0,
        "verified": 0,
        "needs_verification_or_retry": 0,
        "reasons": {},
    }
    if audit_tables:
        merged_audit = pa.concat_tables(audit_tables)
        audit_pq_out = audit_dir / "source_audit.parquet"
        pq.write_table(merged_audit, audit_pq_out, compression="snappy")
        audit_rows = merged_audit.to_pylist()
        reason_counts = Counter(r.get("reason") for r in audit_rows)
        verified_count = sum(1 for r in audit_rows if r.get("verified"))
        source_audit_summary = {
            "audit_tables_merged": len(audit_tables),
            "version_count": len(audit_rows),
            "verified": verified_count,
            "needs_verification_or_retry": len(audit_rows) - verified_count,
            "reasons": dict(sorted(reason_counts.items())),
        }
    runner.atomic_write_json(audit_dir / "source_audit_summary.json", source_audit_summary)

    # 4. Write consolidated M2 manifest & stats
    merged_manifest_rows.sort(key=lambda r: (str(r.get("arxiv_id") or ""), int(r.get("version") or 0)))
    runner.atomic_write_json(parsed_dir / "manifest.json", merged_manifest_rows)

    m2_stats_core = summarize_m2(merged_manifest_rows, merged_pubs)
    code_hashes = sorted({d["stats"].get("code_hash") for d in member_stats_docs if d["stats"].get("code_hash")})
    final_output_bytes = sum(
        p.stat().st_size
        for tbl in ("elements", "hierarchy", "bibtex")
        for p in (parsed_dir / tbl).glob("*.parquet")
    )
    consolidated_stats = {
        "run_id": "team_25000_consolidated",
        "pipeline_version": "0.2.0",
        "code_hash": code_hashes[0] if len(code_hashes) == 1 else code_hashes,
        "code_hashes": code_hashes,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": (
            "completed_with_errors"
            if any(row["status"] not in {"success", "empty_no_tex"} for row in merged_manifest_rows)
            else "completed"
        ),
        "final_output_bytes": final_output_bytes,
        "member_runs": [
            {
                "member_id": d["member_id"],
                "short_name": d["short_name"],
                "run_id": d["stats"].get("run_id"),
                "publications": d["stats"].get("publications"),
                "versions": d["stats"].get("versions"),
                "runtime_sec": d["stats"].get("runtime_sec"),
                "status_counts": d["stats"].get("status_counts"),
            }
            for d in member_stats_docs
        ],
        **m2_stats_core,
    }
    runner.atomic_write_json(parsed_dir / "stats.json", consolidated_stats)

    # 5. Global 5-table structural validation across all merged papers
    validation = validate_project(str(course_dir), str(parsed_dir), str(m1_merged_dir / "publications.parquet"))
    runner.atomic_write_json(parsed_dir / "project_validation.json", validation)
    if not validation["structural_valid"] or validation["errors"]:
        raise RuntimeError(f"Consolidated 5-table validation failed: {validation}")

    # 6. Multi-session Colab CPU benchmark summary
    benchmark = summarize_sessions(session_stats_paths, final_output_dir=parsed_dir)
    benchmark["unique_publications"] = len(merged_pubs)
    benchmark["avg_sec_per_unique_publication"] = (
        benchmark["total_profiler_sec"] / len(merged_pubs)
        if benchmark.get("total_profiler_sec") and merged_pubs
        else None
    )
    runner.atomic_write_json(work_dir / "m2_benchmark_sessions.json", benchmark)

    summary = {
        "members_merged": len(members),
        "m1_publications": len(merged_pubs),
        "m1_references": len(merged_refs),
        "m1_overall_stats_publications_after_dedup": m1_overall_stats.get("dedup_summary", {}).get("publications_after"),
        "course_papers": course_check.get("papers"),
        "course_references": course_check.get("references"),
        "source_audit_summary": source_audit_summary,
        "extracted_table_files_per_member": extracted_counts,
        "m2_status": consolidated_stats["status"],
        "m2_publications": consolidated_stats["publications"],
        "m2_versions": consolidated_stats["versions"],
        "m2_status_counts": consolidated_stats["status_counts"],
        "m2_deduplication": consolidated_stats["deduplication"],
        "validation": validation,
        "benchmark_summary": {k: v for k, v in benchmark.items() if k != "sessions"},
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    runner.atomic_write_json(work_dir / "consolidation_summary.json", summary)

    if drive_out_dir is not None:
        drive_target = Path(drive_out_dir)
        drive_target.mkdir(parents=True, exist_ok=True)
        sync_files: dict[str, str] = {}
        artifacts = [
            (m1_merged_dir / "publications.parquet", "m1_merged/publications.parquet"),
            (m1_merged_dir / "references.parquet", "m1_merged/references.parquet"),
            (m1_merged_dir / "crawl_status.parquet", "m1_merged/crawl_status.parquet"),
            (m1_merged_dir / "overall_stats.json", "m1_merged/overall_stats.json"),
            (course_dir / "papers.parquet", "course_export/papers.parquet"),
            (course_dir / "references.parquet", "course_export/references.parquet"),
            (audit_dir / "source_audit_summary.json", "audit/source_audit_summary.json"),
            (parsed_dir / "manifest.json", "parsed/manifest.json"),
            (parsed_dir / "stats.json", "parsed/stats.json"),
            (parsed_dir / "project_validation.json", "parsed/project_validation.json"),
            (work_dir / "m2_benchmark_sessions.json", "m2_benchmark_sessions.json"),
            (work_dir / "consolidation_summary.json", "consolidation_summary.json"),
        ]
        if (audit_dir / "source_audit.parquet").is_file():
            artifacts.append((audit_dir / "source_audit.parquet", "audit/source_audit.parquet"))
        for src, rel in artifacts:
            if src.is_file():
                sync_files[rel] = runner.atomic_copy(src, drive_target / rel)
        runner.atomic_write_json(
            drive_target / "sync_manifest.json",
            {"files": sync_files, "synced_at_utc": datetime.now(timezone.utc).isoformat()},
        )

    return summary


def main() -> None:
    assert_colab_cpu_only()
    cfg_path = Path(os.environ.get("M2_TEAM_CONFIG", "/content/team_25000_manifest.json"))
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    bundle_path = cfg.get("bundle_path")
    bundle_sha = cfg.get("bundle_sha256")
    if bundle_path and bundle_sha and Path(bundle_path).is_file():
        source_root, _ = runner.install_bundle(bundle_path, "/content/m2_source", bundle_sha)
        marker = source_root / ".editable_installed"
        if not marker.is_file():
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "-e", str(source_root)], check=True)
            marker.write_text("ok\n", encoding="utf-8")
        os.chdir(source_root)
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))

    work_root = Path(cfg.get("work_root", "/content/m2_team_25000"))
    drive_out = Path(cfg.get("drive_consolidated_dir", "/content/drive/MyDrive/arxiv-harvester-m2/team_25000"))
    if not Path("/content/drive/MyDrive").is_dir():
        raise RuntimeError("Google Drive must be mounted at /content/drive/MyDrive for team consolidation")

    summary = consolidate_team(cfg, work_root=work_root, drive_out_dir=drive_out)
    print(
        f"[consolidator] DONE pubs={summary['m1_publications']} versions={summary['m2_versions']} "
        f"structural_valid={summary['validation']['structural_valid']} "
        f"all_colab_cpu={summary['benchmark_summary'].get('all_sessions_colab_cpu')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
