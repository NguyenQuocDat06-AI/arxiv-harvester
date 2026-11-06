"""Durable snapshots of notebook logs and per-run measurements."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .drive_backup import file_hash


def snapshot_file(source, destination):
    """Copy the prefix visible at open time, even when the log is growing."""
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        return
    if source.is_symlink() or destination.is_symlink():
        raise ValueError("Run artifact must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    digest = hashlib.sha256()
    try:
        with source.open("rb") as incoming, temporary.open("wb") as outgoing:
            remaining = os.fstat(incoming.fileno()).st_size
            while remaining:
                chunk = incoming.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise OSError("Run artifact was truncated during snapshot")
                outgoing.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
        if file_hash(temporary) != digest.hexdigest():
            raise OSError("Run artifact checksum mismatch")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def mirror_run_artifacts(run_dir, shard_dir, run_id, durable_dir=None):
    """Keep this run's measurements beside its notebook log, then mirror."""
    run_dir, shard_dir = Path(run_dir), Path(shard_dir)
    if run_dir.name != run_id or Path(run_id).name != run_id:
        raise ValueError("Run artifact directory does not match run ID")
    metrics_dir = shard_dir / "runs" / run_id
    if metrics_dir.exists():
        for source in sorted(metrics_dir.iterdir()):
            if source.is_file() and source.suffix in {".json", ".jsonl"}:
                snapshot_file(source, run_dir / source.name)
    if durable_dir is not None:
        destination = Path(durable_dir) / run_id
        for source in sorted(run_dir.rglob("*")):
            if source.is_file() and not source.name.endswith(".tmp"):
                snapshot_file(source, destination / source.relative_to(run_dir))
