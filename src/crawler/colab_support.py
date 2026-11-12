"""Durable snapshots of notebook logs and per-run measurements."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading

from .drive_backup import file_hash

_SYNC_LOCK = threading.RLock()
_SYNC_STATES = {}


def _signature(path):
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _append_prefix(source, destination, signature, offset, count):
    expected = hashlib.sha256()
    with source.open("rb") as incoming:
        opened = os.fstat(incoming.fileno())
        if (opened.st_dev, opened.st_ino) != signature[:2]:
            return False
        incoming.seek(offset)
        with destination.open("r+b") as outgoing:
            outgoing.seek(offset)
            remaining = count
            while remaining:
                chunk = incoming.read(min(1024*1024, remaining))
                if not chunk:
                    raise OSError("Run log truncated during append")
                outgoing.write(chunk)
                expected.update(chunk)
                remaining -= len(chunk)
    actual = hashlib.sha256()
    with destination.open("rb") as copied:
        copied.seek(offset)
        remaining = count
        while remaining:
            chunk = copied.read(min(1024*1024, remaining))
            if not chunk:
                raise OSError("Drive run log append is incomplete")
            actual.update(chunk)
            remaining -= len(chunk)
    if actual.digest() != expected.digest():
        raise OSError("Drive run log append checksum mismatch")
    return True


def sync_artifact(source, destination, final=False):
    """Verify new append-only bytes; copy mutable or replaced files atomically."""
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or destination.is_symlink():
        raise ValueError("Run artifact must be a regular file")
    if source.resolve() == destination.resolve():
        return
    key = str(destination.resolve())
    with _SYNC_LOCK:
        source_stat = _signature(source)
        previous = _SYNC_STATES.get(key)
        destination_stat = _signature(destination) if destination.is_file() else None
        valid = previous is not None and previous["source"] is not None and destination_stat == previous["destination"]
        if valid and source_stat == previous["source"]:
            if final and file_hash(source) != file_hash(destination):
                raise OSError("Final run artifact checksum mismatch")
            return
        appendable = (valid and source.suffix in {".log", ".jsonl"}
                      and source_stat[:2] == previous["source"][:2]
                      and source_stat[2] > previous["source"][2])
        if appendable:
            offset = destination_stat[2]
            count = source_stat[2]-offset
            try:
                if not _append_prefix(source, destination, source_stat, offset, count):
                    source_stat = snapshot_file(source, destination)
            except BaseException:
                with destination.open("r+b") as outgoing:
                    outgoing.truncate(offset)
                raise
        else:
            source_stat = snapshot_file(source, destination)
        saved_source = source_stat
        _SYNC_STATES[key] = {"source": saved_source, "destination": _signature(destination)}
        if final and file_hash(source) != file_hash(destination):
            raise OSError("Final run artifact checksum mismatch")


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
            stat = os.fstat(incoming.fileno())
            signature = stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
            remaining = stat.st_size
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
        return signature
    finally:
        temporary.unlink(missing_ok=True)


def mirror_run_artifacts(run_dir, shard_dir, run_id, durable_dir=None, final=False):
    """Keep this run's measurements beside its notebook log, then mirror."""
    run_dir, shard_dir = Path(run_dir), Path(shard_dir)
    if run_dir.name != run_id or Path(run_id).name != run_id:
        raise ValueError("Run artifact directory does not match run ID")
    metrics_dir = shard_dir / "runs" / run_id
    if metrics_dir.exists():
        for source in sorted(metrics_dir.iterdir()):
            if source.is_file() and source.suffix in {".json", ".jsonl"}:
                sync_artifact(source, run_dir / source.name, final=final)
    if durable_dir is not None:
        destination = Path(durable_dir) / run_id
        for source in sorted(run_dir.rglob("*")):
            if source.is_file() and not source.name.endswith(".tmp"):
                sync_artifact(source, destination / source.relative_to(run_dir), final=final)
