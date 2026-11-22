"""Extract numeric/schema Book aggregates for the 25,000-paper corpus on Colab CPU.

Reads Drive team_25000 outputs and member resource_samples.jsonl in read-only mode
and writes book_aggregates_25000.json without any paper IDs, raw text, or local paths.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import sys

import pyarrow.parquet as pq


def _aggregate_resource_samples(samples_path: Path, runtime_sec: float | None, window_sec: float = 60.0) -> dict | None:
    if not samples_path.is_file():
        return None
    windows: dict[int, dict[str, list[int]]] = {}
    counts = Counter()
    with samples_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            kind = row.get("kind")
            if kind not in {"rss", "disk"}:
                continue
            elapsed = max(0.0, float(row.get("elapsed_sec", 0.0)))
            bucket = windows.setdefault(int(elapsed // window_sec), {"rss": [], "disk": []})
            val = int(row["rss_bytes" if kind == "rss" else "total_bytes"])
            bucket[kind].append(val)
            counts[kind] += 1
    rows = []
    for idx, bucket in sorted(windows.items()):
        rss, disk = bucket["rss"], bucket["disk"]
        end_sec = (idx + 1) * window_sec
        if runtime_sec is not None:
            end_sec = min(end_sec, float(runtime_sec))
        rows.append({
            "window_start_sec": idx * window_sec,
            "window_end_sec": end_sec,
            "rss_sample_mean_mib": (sum(rss) / len(rss) / 1048576.0) if rss else None,
            "rss_peak_mib": (max(rss) / 1048576.0) if rss else None,
            "disk_peak_bytes": max(disk) if disk else None,
        })
    return {
        "window_sec": window_sec,
        "rss_samples": counts["rss"],
        "disk_samples": counts["disk"],
        "rows": rows,
    }


def _arrow_schema_rows(schema) -> list[dict]:
    return [{"column": f.name, "type": str(f.type), "nullable": bool(f.nullable)} for f in schema]


def main() -> None:
    drive_root = Path(os.environ.get("M2_DRIVE_ROOT", "/content/drive/MyDrive/arxiv-harvester-m2"))
    team_dir = drive_root / "team_25000"
    manifest_cfg_path = Path(os.environ.get("M2_TEAM_CONFIG", "/content/team_25000_manifest.json"))
    if not team_dir.is_dir():
        raise FileNotFoundError(f"Missing Drive team_25000 dir: {team_dir}")

    m1_dir = team_dir / "m1_merged"
    course_dir = team_dir / "course_export"
    audit_path = team_dir / "audit/source_audit.parquet"

    pubs = pq.read_table(m1_dir / "publications.parquet").to_pylist()
    refs = pq.read_table(m1_dir / "references.parquet").to_pylist()
    obs = pq.read_table(m1_dir / "crawl_status.parquet").to_pylist()
    audit_rows = pq.read_table(audit_path).to_pylist()
    overall_stats = json.loads((m1_dir / "overall_stats.json").read_text(encoding="utf-8"))

    versions = [{"arxiv_id": p["id"], **v} for p in pubs for v in (p.get("versions") or [])]
    verified_map = {(a["arxiv_id"], a["version"]): bool(a.get("verified")) for a in audit_rows}
    eligible = [
        p for p in pubs
        if p.get("versions")
        and all(v.get("source_status") == "success" and verified_map.get((p["id"], v.get("version"))) for v in p["versions"])
    ]
    before_totals = [sum(v.get("size_before_bytes") or 0 for v in p["versions"]) for p in eligible]
    after_totals = [sum(v.get("size_after_bytes") or 0 for v in p["versions"]) for p in eligible]
    sum_before = sum(before_totals)
    sum_after = sum(after_totals)

    complete_sources = {
        p["id"] for p in pubs
        if p.get("versions") and all(verified_map.get((p["id"], v.get("version")), False) for v in p["versions"])
    }
    complete_refs = {o["arxiv_id"] for o in obs if o.get("reference_status") in {"success", "empty"}}
    ref_counts = Counter(r["arxiv_id"] for r in refs)
    version_hist = Counter(str(len(p.get("versions") or [])) for p in pubs)
    sorted_hist = {k: version_hist[k] for k in sorted(version_hist, key=int)}

    metadata_missing = {
        key: sum(p.get(key) in (None, "", []) for p in pubs) / len(pubs)
        for key in ("title", "authors", "published", "doi", "venue")
    }
    ref_missing = {
        key: (sum(r.get(key) in (None, "", []) for r in refs) / len(refs) if refs else None)
        for key in ("ref_arxiv_id", "ref_title", "ref_authors", "ref_submission_date", "ref_s2_id")
    }

    schemas = {
        "papers": _arrow_schema_rows(pq.ParquetFile(course_dir / "papers.parquet").schema_arrow),
        "references": _arrow_schema_rows(pq.ParquetFile(course_dir / "references.parquet").schema_arrow),
    }
    for src_root in sorted(Path("/content/m2_source").glob("*")):
        if (src_root / "src").is_dir() and str(src_root) not in sys.path:
            sys.path.insert(0, str(src_root))
            break
    try:
        from src.parser.storage import SCHEMAS as M2_SCHEMAS
        for name, sch in M2_SCHEMAS.items():
            schemas[name] = _arrow_schema_rows(sch)
    except ImportError:
        pass

    m1_agg = {
        "version_histogram": sorted_hist,
        "version_status": dict(Counter(v.get("source_status") for v in versions)),
        "source_audit": dict(Counter(a.get("reason") for a in audit_rows)),
        "source_verified": sum(1 for a in audit_rows if a.get("verified")),
        "metadata_missing_fraction": metadata_missing,
        "references_missing_fraction": ref_missing,
        "reference_status": dict(Counter(o.get("reference_status") for o in obs)),
        "working_reference_rows": len(refs),
        "arxiv_reference_rows": pq.ParquetFile(course_dir / "references.parquet").metadata.num_rows,
        "verified_reference_papers": len(complete_refs),
        "mean_references_verified_papers": (sum(ref_counts[k] for k in complete_refs) / len(complete_refs)) if complete_refs else None,
        "eligible_size_papers": len(eligible),
        "mean_before_bytes": (sum_before / len(eligible)) if eligible else None,
        "mean_after_bytes": (sum_after / len(eligible)) if eligible else None,
        "source_reduction": (1.0 - sum_after / sum_before) if sum_before else None,
        "papers_with_all_sources_verified": len(complete_sources),
        "papers_with_sources_and_s2_verified": len(complete_sources & complete_refs),
        "missing_version_dates": sum(v.get("created") is None for v in versions),
        "schemas": schemas,
    }

    # Extract 60s M2 resource profiles keyed by anonymous member short name
    team_cfg = json.loads(manifest_cfg_path.read_text(encoding="utf-8"))
    short_by_id = {m["member_id"]: m["short_name"] for m in team_cfg["members"]}
    m2_resource_profiles: dict[str, dict | None] = {}
    for m in team_cfg["members"]:
        mid = m["member_id"]
        short = m["short_name"]
        gen = m["generation"]
        full_dir = drive_root / "members" / mid / gen / "full"
        st_path = full_dir / "stats.json"
        runtime_sec = json.loads(st_path.read_text(encoding="utf-8")).get("runtime_sec") if st_path.is_file() else None
        sample_files = sorted((full_dir / "runs").glob("*/resource_samples.jsonl"))
        profile = _aggregate_resource_samples(sample_files[-1], runtime_sec, window_sec=60.0) if sample_files else None
        m2_resource_profiles[short] = profile

    # Summarize M1 Colab sessions anonymously
    m1_colab_sessions = []
    for row in overall_stats.get("member_breakdown", []):
        mid = row["member_id"]
        short = short_by_id.get(mid, mid)
        env = row.get("environment") or {}
        if not row.get("stats_usable_for_shard"):
            resume_stats_path = drive_root / "m1_resume_24120470/shard_stats.json"
            if resume_stats_path.is_file():
                rst = json.loads(resume_stats_path.read_text(encoding="utf-8"))
                renv = rst.get("environment") or {}
                rmem = rst.get("memory") or {}
                rres = rst.get("results") or {}
                m1_colab_sessions.append({
                    "session_label": f"M1-{short}-resume",
                    "publications_count": row.get("publications_count"),
                    "processed_this_run": rres.get("processed_this_run"),
                    "status": rst.get("status"),
                    "runtime_sec": rst.get("runtime_sec"),
                    "peak_rss_mb": rmem.get("peak_rss_mb"),
                    "avg_rss_mb": rmem.get("avg_rss_mb"),
                    "colab_cpu": bool(renv.get("is_google_colab") and renv.get("cpu_only")),
                })
            continue
        res = row.get("results") or {}
        m1_colab_sessions.append({
            "session_label": f"M1-{short}",
            "publications_count": row.get("publications_count"),
            "processed_this_run": res.get("processed_this_run"),
            "status": "completed" if not (res.get("failed")) else "completed_with_errors",
            "runtime_sec": row.get("runtime_sec"),
            "peak_rss_mb": row.get("peak_rss_mb"),
            "avg_rss_mb": row.get("avg_rss_mb"),
            "colab_cpu": bool(env.get("is_google_colab") and env.get("cpu_only")),
        })

    payload = {
        "m1": m1_agg,
        "m2_resource_profiles": m2_resource_profiles,
        "m1_colab_sessions": m1_colab_sessions,
    }
    out_path = team_dir / "book_aggregates_25000.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, out_path)
    print("WROTE:", out_path, "bytes:", out_path.stat().st_size, "profiles:", {k: (v["rss_samples"] if v else None) for k, v in m2_resource_profiles.items()}, flush=True)


if __name__ == "__main__":
    main()
