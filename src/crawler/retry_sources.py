"""Retry audited revisions and write repaired shards."""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import math
import os
import re
import time
import uuid
import json
from pathlib import Path
import shutil
import pyarrow.parquet as pq
from .records import base_id, merge_publications
from .source_downloader import download_and_clean_source, get_dir_size_bytes
from .storage import save_publications_parquet
from .profiler import _write_json_atomic


def _verified_source(row: dict) -> dict | None:
    identifier = row["arxiv_id"] + row["version"]
    raw = Path(row["raw_dir"])
    try:
        evidence = json.loads((raw / "manifests" / (identifier.replace("/", "_") + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if evidence.get("version_id") != identifier:
        return None
    directory = raw / "unzipped" / row["arxiv_id"].replace("/", "_") / row["version"]
    if not directory.is_dir() or directory.is_symlink():
        return None
    files = list(directory.rglob("*"))
    if any(p.is_symlink() or (p.is_file() and p.suffix.lower() not in {".tex", ".bib"}) for p in files):
        return None
    tex = any(p.is_file() and p.suffix.lower() == ".tex" for p in files)
    if evidence.get("status") == "success":
        valid = tex and evidence.get("evidence") == "tex_extracted" and get_dir_size_bytes(directory) == evidence.get("size_after_bytes")
    else:
        valid = (not tex and evidence.get("status") in {"pdf_only", "no_latex"}
                 and evidence.get("evidence") in {"pdf_header", "archive_without_tex"})
    return evidence if valid else None


def retry_sources(manifest: str, output_dir: str, execute=False, limit: int | None = None,
                  read_timeout_sec: float = 45.0, download_attempts: int = 2,
                  min_free_gb: float = 4.0, prefer_known_sources: bool = False,
                  source_rate_limit_sec: float = 3.0) -> dict:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if not math.isfinite(read_timeout_sec) or read_timeout_sec <= 0:
        raise ValueError("read_timeout_sec must be positive and finite")
    if not math.isfinite(source_rate_limit_sec) or source_rate_limit_sec < 1:
        raise ValueError("source_rate_limit_sec must be >= 1")
    if isinstance(download_attempts, bool) or not isinstance(download_attempts, int) or download_attempts < 1 or not math.isfinite(min_free_gb) or min_free_gb < 0:
        raise ValueError("Invalid attempts or free disk threshold")
    selected = {}
    with open(manifest, encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if not re.fullmatch(r'v[1-9]\d*', str(row["version"])):
                raise ValueError("Invalid retry version")
            selected[(row["arxiv_id"], row["version"])] = row
    rows = list(selected.values())
    if prefer_known_sources:
        rows.sort(key=lambda row: row.get("source_status") != "success")
    report = {"planned": min(len(rows), limit) if limit else len(rows), "manifest_versions": len(rows),
              "executed": 0, "reused": 0, "failed": 0, "results": [], "execute": execute}
    if not execute:
        report["message"] = "Plan only; pass --execute to make requests and write repaired shards"
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        output = Path(output_dir)
        run_dir = output / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        report.update(run_id=run_id, status="running", events_file=str(run_dir / "events.jsonl"),
                      pid=os.getpid(), started_at_utc=datetime.now(timezone.utc).isoformat())
        started = time.perf_counter()
        def persist():
            report["elapsed_sec"] = round(time.perf_counter() - started, 3)
            _write_json_atomic(str(output / "retry_report.json"), report)
            _write_json_atomic(str(run_dir / "retry_report.json"), report)
        persist()
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["source_file"]].append(row)
        for source_path, jobs in grouped.items():
            source = Path(source_path)
            destination = Path(output_dir) / source.parent.name
            if destination.resolve() == source.parent.resolve():
                raise ValueError("Use a separate output directory to preserve the original shard")
            destination.mkdir(parents=True, exist_ok=True)
            records = {base_id(p): p for p in pq.ParquetFile(source).read().to_pylist()}
            if (destination / "publications.parquet").exists():
                for paper in pq.ParquetFile(destination / "publications.parquet").read().to_pylist():
                    records[base_id(paper)] = merge_publications(records.get(base_id(paper)), paper)
            for row in jobs:
                if (output / "STOP").exists():
                    report.update(status="stopped_by_request", next_version=row["arxiv_id"] + row["version"])
                    persist()
                    return report
                result = _verified_source(row)
                reused = result is not None
                if reused:
                    report["reused"] += 1
                else:
                    if limit and report["executed"] >= limit:
                        break
                    raw = Path(row["raw_dir"])
                    raw.mkdir(parents=True, exist_ok=True)
                    if shutil.disk_usage(raw).free < min_free_gb * 1024**3:
                        report.update(status="stopped_low_disk", next_version=row["arxiv_id"] + row["version"])
                        persist()
                        return report
                    persist()
                    try:
                        result = download_and_clean_source(row["arxiv_id"] + row["version"],
                                                          str(raw / "sources"), str(raw / "unzipped"), rate_limit_sec=source_rate_limit_sec,
                                                          max_attempts=download_attempts, read_timeout_sec=read_timeout_sec)
                    except Exception as error:
                        result = {"status":"error", "error_message":str(error)}
                    report["executed"] += 1
                    report["failed"] += result["status"] not in {"success", "pdf_only", "no_latex"}
                update = {"id": row["arxiv_id"], "versions": [{"version": row["version"],
                          "source_status": result["status"], "size_before_bytes": result.get("size_before_bytes"),
                          "size_after_bytes": result.get("size_after_bytes")} ]}
                records[row["arxiv_id"]] = merge_publications(records[row["arxiv_id"]], update)
                event = {"arxiv_id": row["arxiv_id"], "version": row["version"], "reused":reused, **result}
                with (run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                report["results"].append(event)
                report["results"] = report["results"][-100:]
                report["last_version"] = row["arxiv_id"] + row["version"]
                save_publications_parquet(list(records.values()), str(destination / "publications.parquet"))
                persist()
                print(json.dumps({"version":report["last_version"], "status":result["status"], "executed":report["executed"], "reused":report["reused"]}), flush=True)
                if result.get("rate_limited"):
                    for name in ("references.parquet", "crawl_status.parquet"):
                        if (source.parent / name).exists() and not (destination / name).exists():
                            shutil.copyfile(source.parent / name, destination / name)
                    report.update(status="paused_rate_limit", retry_after_sec=result.get("retry_after_sec"))
                    persist()
                    return report
            for name in ("references.parquet", "crawl_status.parquet"):
                if (source.parent / name).exists() and not (destination / name).exists():
                    shutil.copyfile(source.parent / name, destination / name)
            _write_json_atomic(str(destination / "repair_provenance.json"), {
                "input_publications": str(source), "original_stats": str(source.parent / "stats.json"),
                "note": "Original run statistics are not copied as measurements of this repair."})
        report["status"] = "completed_with_errors" if report["failed"] else "completed_scope"
        persist()
    _write_json_atomic(str(Path(output_dir) / "retry_report.json"), report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--read-timeout-sec", type=float, default=45.0)
    parser.add_argument("--download-attempts", type=int, default=2)
    parser.add_argument("--source-rate-limit-sec", type=float, default=3.0)
    parser.add_argument("--min-free-gb", type=float, default=4.0)
    parser.add_argument("--prefer-known-sources", action="store_true")
    parser.add_argument("--rate-state-dir")
    args = vars(parser.parse_args(argv))
    state_dir = args.pop("rate_state_dir") or str(Path(args["output_dir"]) / "_request_state")
    from .request_policy import network_runtime
    with network_runtime(state_dir):
        print(json.dumps(retry_sources(**args), ensure_ascii=True))


if __name__ == "__main__":
    main()
