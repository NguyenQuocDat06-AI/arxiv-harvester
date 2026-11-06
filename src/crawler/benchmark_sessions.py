"""Summarize saved benchmark sessions without changing their recorded metrics."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid nonnegative measurement: {value!r}")
    return value


def _total(values):
    return sum(values) if all(value is not None for value in values) else None


def _maximum(values):
    return max(values) if all(value is not None for value in values) else None


def summarize_sessions(paths: list[str | Path], final_output_dir: str | Path | None = None) -> dict:
    if not paths:
        raise ValueError("Supply at least one stats.json")
    rows, seen, duplicates, stages = [], {}, 0, set()
    for value in paths:
        path = Path(value)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("is_mock") is True or data.get("dry_run") is True:
            raise ValueError("Mock/dry-run statistics cannot be benchmark evidence")
        run_id = data.get("run_id")
        if not run_id:
            raise ValueError(f"Missing run_id in {path}")
        digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        if run_id in seen:
            if seen[run_id] != digest:
                raise ValueError(f"Conflicting statistics for run {run_id}")
            duplicates += 1
            continue
        seen[run_id] = digest
        metadata_path = path.with_name("run_metadata.json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        if metadata.get("run_id") != run_id:
            metadata = {}
        stage = "M2" if "pipeline_version" in data or "publication_coverage" in data else "M1"
        stages.add(stage)
        env, memory, disk = data.get("environment", {}), data.get("memory", {}), data.get("disk", {})
        results = data.get("results", {})
        scale = memory.get("bytes_per_mb")
        scale = _number(scale) / 1024**2 if scale else None
        peak = _number(memory.get("peak_rss_mb"))
        average = _number(memory.get("avg_rss_mb"))
        rows.append({
            "run_id": run_id, "stage": stage, "stats_file": str(path), "stats_sha256": digest,
            "status": data.get("status"), "resumed": data.get("resumed"),
            "started_at_utc": data.get("started_at_utc"), "finished_at_utc": data.get("finished_at_utc"),
            "source_revision": metadata.get("source_commit") or data.get("source_code_hash") or data.get("code_hash"),
            "colab_cpu": bool(env.get("is_google_colab") and env.get("cpu_only")),
            "cpu_count_logical": env.get("cpu_count_logical"), "python_version": env.get("python_version"),
            "processed_attempts": _number(data.get("processed_this_run", results.get("processed_this_run"))),
            "publications_reused": _number(data.get("reused")),
            "versions_reused": _number(results.get("versions_reused")),
            "profiler_sec": _number(data.get("runtime_sec")),
            "child_wall_sec": _number(metadata.get("child_wall_sec")),
            "peak_rss_mib": peak * scale if peak is not None and scale is not None else None,
            "avg_rss_mib": average * scale if average is not None and scale is not None else None,
            "peak_disk_bytes": _number(disk.get("peak_bytes")),
            "final_disk_bytes": _number(disk.get("final_bytes")),
            "intervals": {key: data.get("run_args", {}).get(key) for key in
                          ("rate_limit_sec", "source_rate_limit_sec", "s2_rate_limit_sec")},
        })
    if len(stages) != 1:
        raise ValueError("Summarize M1 and M2 in separate reports")
    durations = [row["profiler_sec"] for row in rows]
    total_profiler = _total(durations)
    complete_ram = all(row["avg_rss_mib"] is not None for row in rows)
    weighted_ram = (sum(row["avg_rss_mib"] * row["profiler_sec"] for row in rows) / total_profiler
                    if complete_ram and total_profiler else None)
    windows = []
    for row in rows:
        if row["started_at_utc"] and row["finished_at_utc"]:
            start = datetime.fromisoformat(row["started_at_utc"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(row["finished_at_utc"].replace("Z", "+00:00"))
            if start.tzinfo is None or end.tzinfo is None or end < start:
                raise ValueError("Session timestamps must be timezone-aware and ordered")
            windows.append((start, end))
    windows.sort()
    overlap = any(start < max(end for _, end in windows[:index])
                  for index, (start, _) in enumerate(windows) if index)
    output_bytes = None
    if final_output_dir is not None:
        from .profiler import dir_size_bytes
        directory = Path(final_output_dir)
        if not directory.is_dir():
            raise NotADirectoryError(directory)
        output_bytes = dir_size_bytes(str(directory))
    return {
        "stage": next(iter(stages)), "sessions": rows, "duplicate_run_files_skipped": duplicates,
        "all_sessions_colab_cpu": all(row["colab_cpu"] for row in rows),
        "source_revisions": sorted({row["source_revision"] for row in rows if row["source_revision"]}),
        "session_timestamps_complete": len(windows) == len(rows), "sessions_overlap": overlap,
        "total_profiler_sec": total_profiler,
        "total_child_wall_sec": _total([row["child_wall_sec"] for row in rows]),
        "processed_attempts": _total([row["processed_attempts"] for row in rows]),
        "unique_publications": None,
        "max_session_peak_rss_mib": _maximum([row["peak_rss_mib"] for row in rows]),
        "session_time_weighted_avg_rss_mib": weighted_ram,
        "max_session_peak_disk_bytes": _maximum([row["peak_disk_bytes"] for row in rows]),
        "final_output_bytes": output_bytes,
        "coverage_note": "Attempt counts may repeat papers; verify unique IDs, versions and source/reference audits separately.",
        "timing_note": "Recorded runtime already includes retry/delay. Session sums exclude time between sessions and are not calendar wall time.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--final-output-dir", type=Path)
    args = parser.parse_args(argv)
    result = summarize_sessions(args.stats, args.final_output_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "sessions"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
