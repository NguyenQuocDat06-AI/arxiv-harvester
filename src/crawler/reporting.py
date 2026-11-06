"""Read saved data and measurements for report notebooks."""
from __future__ import annotations
from pathlib import Path
import json
import os
import hashlib
import pandas as pd
import pyarrow.parquet as pq


def load_m1(directory: str | Path | None = None) -> dict:
    path = Path(directory or os.environ.get("ARXIV_M1_DATA_DIR", "data/processed")).resolve()
    if not (path / "publications.parquet").exists() or not (path / "references.parquet").exists():
        raise FileNotFoundError(f"M1 inputs missing at {path}; set ARXIV_M1_DATA_DIR to saved working tables")
    paper_table = pq.ParquetFile(path / "publications.parquet").read()
    ref_table = pq.ParquetFile(path / "references.parquet").read()
    papers = pd.DataFrame(paper_table.to_pylist(), columns=paper_table.column_names)
    refs = pd.DataFrame(ref_table.to_pylist(), columns=ref_table.column_names)
    observations = pd.DataFrame(pq.ParquetFile(path / "crawl_status.parquet").read().to_pylist()) if (path / "crawl_status.parquet").exists() else pd.DataFrame()
    stats_path = next((p for p in (path / "overall_stats.json", path / "stats.json") if p.exists()), None)
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path else {}
    if stats.get("is_mock") is True:
        raise ValueError("Report refuses mock data")
    versions = pd.DataFrame([{"arxiv_id": p["id"], **v} for p in papers.to_dict("records") for v in p.get("versions") or []],
                            columns=["arxiv_id", "version", "created", "size_before_bytes", "size_after_bytes", "source_status"])
    audit_path = path / "source_audit.parquet"
    audit = pd.DataFrame(pq.ParquetFile(audit_path).read().to_pylist()) if audit_path.exists() else pd.DataFrame()
    return {"directory": path, "papers": papers, "references": refs, "versions": versions,
            "observations": observations, "stats": stats, "source_audit": audit,
            "provenance": "mock" if stats.get("is_mock") is True else "recorded real" if stats.get("is_mock") is False else "not supplied/unknown"}


def load_m2(directory: str | Path | None = None) -> dict:
    path = Path(directory or os.environ.get("ARXIV_M2_DATA_DIR", "data/parsed")).resolve()
    for name in ("manifest.json", "stats.json"):
        if not (path / name).exists():
            raise FileNotFoundError(f"M2 inputs missing at {path}; set ARXIV_M2_DATA_DIR")
    stats = json.loads((path / "stats.json").read_text(encoding="utf-8"))
    if stats.get("is_mock") is True:
        raise ValueError("Report refuses mock data")
    if stats.get("status") not in {"completed", "completed_with_errors"}:
        raise ValueError("Report needs a finished parser run; latest run failed or was interrupted")
    manifest = pd.DataFrame(json.loads((path / "manifest.json").read_text(encoding="utf-8")))
    if stats.get("versions") != len(manifest):
        raise ValueError("Parser manifest does not match the recorded run version count")
    project_validation = None
    quality_file = path / "project_validation.json"
    if quality_file.exists():
        project_validation = json.loads(quality_file.read_text(encoding="utf-8"))
        provenance = project_validation.get("inputs", {})
        digest = hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()
        if provenance.get("parser_run_id") != stats.get("run_id") or provenance.get("manifest_sha256") != digest:
            raise ValueError("Project validation belongs to a different parser run; regenerate it before building reports")
    working = []
    for file in sorted((path / "working").glob("*.json"))[:2]:
        working.append(json.loads(file.read_text(encoding="utf-8")))
    return {"directory": path, "stats": stats, "manifest": manifest, "working": working,
            "project_validation": project_validation}


def run_table(directory: Path) -> pd.DataFrame:
    paths = sorted((directory / "runs").glob("*/stats.json"))
    if not paths and (directory / "stats.json").exists():
        paths = [directory / "stats.json"]
    rows = []
    for path in paths:
        stats = json.loads(path.read_text(encoding="utf-8"))
        if stats.get("is_mock") is True:
            continue
        env, mem, disk = stats.get("environment", {}), stats.get("memory", {}), stats.get("disk", {})
        metadata_path = path.with_name("run_metadata.json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        if metadata.get("run_id") != stats.get("run_id"):
            metadata = {}
        rows.append({"run_id": stats.get("run_id", path.parent.name), "status": stats.get("status"),
                     "colab_cpu": bool(env.get("is_google_colab") and env.get("cpu_only")),
                     "runtime_sec": stats.get("runtime_sec"), "runtime_scope": stats.get("runtime_scope", "profiler scope; see run configuration"),
                     "disk_scope": stats.get("disk_scope", "watched directories in stats.json"),
                     "processed_this_run": stats.get("processed_this_run", stats.get("results", {}).get("processed_this_run")),
                     "assigned_ids": stats.get("results", {}).get("total_ids"),
                     "child_wall_sec": metadata.get("child_wall_sec"),
                     "arxiv_metadata_interval_sec": stats.get("run_args", {}).get("rate_limit_sec"),
                     "arxiv_source_interval_sec": stats.get("run_args", {}).get("source_rate_limit_sec"),
                     "publications_reused": stats.get("reused"), "versions_reused": stats.get("results", {}).get("versions_reused"),
                     "peak_rss_mb": mem.get("peak_rss_mb"), "avg_rss_mb": mem.get("avg_rss_mb"),
                     "peak_disk_bytes": disk.get("peak_bytes"), "final_disk_bytes": disk.get("final_bytes")})
    return pd.DataFrame(rows)
