"""Verified incremental archives for a local crawl workspace."""
from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import time
import uuid

from .profiler import _write_json_atomic
from .request_policy import LocalMutex

logger = logging.getLogger(__name__)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not isinstance(name, str) or path.is_absolute() or path.as_posix() != name
            or ".." in path.parts or "\\" in name or ":" in name
            or not path.parts or path.parts[0] not in {"raw", "shard"}):
        raise ValueError("Invalid backup path")
    return path


def walk(root):
    if root.is_symlink():
        raise ValueError("Backup input is a symlink")
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Backup input contains a symlink")
        if not any(".staging-" in part or part == ".drive_backup_staging" for part in path.parts) and not path.name.endswith(".tmp"):
            yield path


def remove_inside(root, path):
    if not path.resolve().is_relative_to(root.resolve()) or path.resolve() == root.resolve():
        raise ValueError("Backup removal escapes staging")
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


class CheckpointBackup:
    def __init__(self, raw_dir, shard_dir, backup_dir):
        self.raw, self.shard, self.directory = map(lambda p: Path(p).resolve(), (raw_dir, shard_dir, backup_dir))
        if any(self.directory.is_relative_to(p) or p.is_relative_to(self.directory) for p in (self.raw, self.shard)):
            raise ValueError("Backup directory must be outside raw/shard")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.staging_directory = self.shard / ".drive_backup_staging"
        self.previous = self._head()
        self.signatures = {}
        self.commits = 0

    def _head(self):
        path = self.directory / "HEAD.json"
        if not path.exists():
            return None
        head = json.loads(path.read_text(encoding="utf-8"))
        return self._record(head["generation"], head["sha256"])

    def _record(self, generation, expected):
        if not re.fullmatch(r"[0-9a-f]{32}", generation):
            raise ValueError("Invalid backup generation")
        path = self.directory / (generation + ".json")
        if file_hash(path) != expected:
            raise ValueError("Backup commit checksum mismatch")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("format") != 1 or record.get("generation") != generation:
            raise ValueError("Invalid backup commit")
        record["record_sha256"] = expected
        return record

    def save(self, paper_ids=(), include_outputs=False):
        with LocalMutex("drive-backup:" + str(self.directory), timeout=0):
            return self._save(paper_ids, include_outputs)

    def _save(self, paper_ids, include_outputs):
        head = self._head()
        if (head or {}).get("generation") != (self.previous or {}).get("generation"):
            raise RuntimeError("Backup changed in another runtime; stop this writer")
        state_path = self.shard / "_checkpoint/state.json"
        state_bytes = state_path.read_bytes()
        state = json.loads(state_bytes)
        parts = state["parts"]
        if self.previous:
            previous = self.previous
            if state["member_id"] != previous["member_id"] or state["id_range"] != previous["id_range"]:
                raise ValueError("Backup belongs to another member/range")
            prefix = {kind: parts.get(kind, [])[:count] for kind, count in previous["part_counts"].items()}
            if (hashlib.sha256(json.dumps(prefix, sort_keys=True).encode()).hexdigest() != previous["parts_sha256"]
                    or state["next_batch"] < previous["next_batch"]):
                raise ValueError("Local checkpoint does not extend the committed backup")
            if (state["next_batch"] == previous["next_batch"]
                    and hashlib.sha256(state_bytes).hexdigest() != previous["checkpoint_sha256"]):
                raise ValueError("Local checkpoint differs from backup at the same batch")
        files = {"shard/_checkpoint/state.json": state_path}
        ids = {str(p).replace("/", "_") for p in paper_ids}
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) or p in {".", ".."} for p in ids):
            raise ValueError("Invalid backup paper ID")
        for kind, names in parts.items():
            old = (self.previous or {}).get("part_counts", {}).get(kind, 0)
            for name in names[old:]:
                if not re.fullmatch(r"(?:publications|references|statuses)_\d+\.parquet", name):
                    raise ValueError("Invalid checkpoint part")
                path = self.shard / "_checkpoint" / name
                files["shard/_checkpoint/" + name] = path
                if kind == "publications":
                    import pyarrow.parquet as pq
                    ids.update(row["id"].replace("/", "_") for row in pq.ParquetFile(path).read(columns=["id"]).to_pylist())
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) or p in {".", ".."} for p in ids):
            raise ValueError("Invalid checkpoint paper ID")
        full_raw = self.previous is None
        raw_paths = list(walk(self.raw)) if full_raw else []
        if not full_raw:
            for identifier in sorted(ids):
                directory = self.raw / "unzipped" / identifier
                if directory.exists():
                    raw_paths.append(directory)
                    raw_paths.extend(walk(directory))
            prefixes = tuple(identifier + "v" for identifier in ids)
            for folder in (self.raw / "sources", self.raw / "manifests"):
                if folder.exists() and prefixes:
                    raw_paths.extend(path for path in folder.iterdir() if path.name.startswith(prefixes))
        directories = {"raw", "shard"}
        for path in raw_paths:
            name = "raw/" + path.relative_to(self.raw).as_posix()
            if path.is_dir():
                directories.add(name)
            elif path.is_file():
                files[name] = path
        if include_outputs or not self.previous:
            for path in walk(self.shard):
                if path.is_file() and "_checkpoint" not in path.relative_to(self.shard).parts:
                    # The profiler still appends until this run's stats are exported.
                    if (path.name == "resource_samples.jsonl" and path.parent.parent.name == "runs"
                            and not (path.parent / "stats.json").is_file()):
                        continue
                    files["shard/" + path.relative_to(self.shard).as_posix()] = path
        signatures = {name: (path.stat().st_mtime_ns, path.stat().st_size) for name, path in files.items()}
        files = {name: path for name, path in files.items()
                 if name.startswith("raw/") or self.signatures.get(name) != signatures[name]}
        if not files and not ids:
            return self.summary()
        manifest = {"files": {}, "directories": sorted(directories), "replace_raw_ids": sorted(ids), "full_raw": full_raw}
        for name, path in files.items():
            safe_name(name)
            if path.is_symlink():
                raise ValueError("Backup file is a symlink")
            manifest["files"][name] = {"sha256": file_hash(path), "size": path.stat().st_size}
        generation = uuid.uuid4().hex
        started = time.perf_counter()
        self.staging_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="batch-", dir=self.staging_directory) as temporary:
            archive = Path(temporary) / (generation + ".tar.gz")
            with tarfile.open(archive, "w:gz", compresslevel=1) as target:
                for name, path in files.items():
                    target.add(path, arcname=name, recursive=False)
                payload = json.dumps(manifest, sort_keys=True).encode()
                info = tarfile.TarInfo("backup_manifest.json")
                info.size = len(payload)
                target.addfile(info, io.BytesIO(payload))
            self._verify_archive(archive)
            incoming = self.directory / (generation + ".tar.gz.tmp")
            expected = file_hash(archive)
            shutil.copyfile(archive, incoming)
            if file_hash(incoming) != expected:
                raise OSError("Drive archive checksum mismatch; previous checkpoint retained")
            incoming.replace(self.directory / archive.name)
        prefix = {kind: list(names) for kind, names in parts.items()}
        record = {"format": 1, "generation": generation, "archive_sha256": expected,
                  "parent": self.previous["generation"] if self.previous else None,
                  "parent_sha256": self.previous["record_sha256"] if self.previous else None,
                  "member_id": state["member_id"], "id_range": state["id_range"], "next_batch": state["next_batch"],
                  "checkpoint_sha256": hashlib.sha256(state_bytes).hexdigest(),
                  "part_counts": {kind: len(names) for kind, names in parts.items()},
                  "parts_sha256": hashlib.sha256(json.dumps(prefix, sort_keys=True).encode()).hexdigest(),
                  "done_ids": len(state["done_ids"]), "created_at": time.time()}
        commit_path = self.directory / (generation + ".json")
        _write_json_atomic(str(commit_path), record)
        record_hash = file_hash(commit_path)
        if json.loads(commit_path.read_text(encoding="utf-8")) != record:
            raise OSError("Drive commit verification failed")
        _write_json_atomic(str(self.directory / "HEAD.json"), {"generation": generation, "sha256": record_hash})
        self.previous = {**record, "record_sha256": record_hash}
        self.signatures.update(signatures)
        self.commits += 1
        logger.info("Drive backup đã xác minh: %s | %d file, %d ID trong checkpoint | %.2fs",
                    generation[:8], len(files), record["done_ids"], time.perf_counter() - started)
        return self.summary()

    def summary(self):
        return {"directory": str(self.directory), "generation": (self.previous or {}).get("generation"),
                "checkpoint_ids": (self.previous or {}).get("done_ids", 0), "commits_this_run": self.commits}

    @staticmethod
    def _verify_archive(path, destination=None):
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            names = [row.name for row in members]
            if len(names) != len(set(names)) or names.count("backup_manifest.json") != 1:
                raise ValueError("Invalid backup archive members")
            manifest_member = archive.getmember("backup_manifest.json")
            if not manifest_member.isfile() or manifest_member.size > 32 * 1024**2:
                raise ValueError("Invalid backup manifest")
            manifest = json.load(archive.extractfile(manifest_member))
            if set(names) != set(manifest["files"]) | {"backup_manifest.json"}:
                raise ValueError("Backup manifest/member mismatch")
            for name in manifest["directories"]:
                safe_name(name)
            for row in members:
                if not row.isfile():
                    raise ValueError("Backup archive contains a non-file")
                if row.name == "backup_manifest.json":
                    continue
                safe_name(row.name)
                info = manifest["files"][row.name]
                if row.size != info["size"]:
                    raise ValueError("Backup file size mismatch")
                digest = hashlib.sha256()
                with archive.extractfile(row) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != info["sha256"]:
                    raise ValueError("Backup file checksum mismatch")
            if destination is not None:
                raw = destination / "raw"
                if manifest["full_raw"] and raw.exists():
                    remove_inside(destination, raw)
                for identifier in manifest["replace_raw_ids"]:
                    if not re.fullmatch(r"[A-Za-z0-9_.-]+", identifier) or identifier in {".", ".."}:
                        raise ValueError("Invalid backup paper ID")
                    remove_inside(destination, raw / "unzipped" / identifier)
                    for folder in (raw / "sources", raw / "manifests"):
                        if folder.exists():
                            for entry in list(folder.iterdir()):
                                if entry.name.startswith(identifier + "v"):
                                    remove_inside(destination, entry)
                for name in manifest["directories"]:
                    (destination / name).mkdir(parents=True, exist_ok=True)
                for row in members:
                    name = row.name
                    if name == "backup_manifest.json":
                        continue
                    target = destination / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(row) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    if file_hash(target) != manifest["files"][name]["sha256"]:
                        raise OSError("Restored file checksum mismatch")
            return manifest

    def restore(self, workspace):
        target = Path(workspace).resolve()
        if target.exists() and any(target.iterdir()):
            raise FileExistsError("Restore requires an empty local workspace")
        if not self.previous:
            return False
        chain, seen = [], set()
        record = self.previous
        while record:
            if record["generation"] in seen:
                raise ValueError("Backup chain contains a cycle")
            seen.add(record["generation"])
            chain.append(record)
            record = self._record(record["parent"], record["parent_sha256"]) if record["parent"] else None
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=target.parent) as temporary:
            staging = Path(temporary) / "workspace"
            staging.mkdir()
            for record in reversed(chain):
                remote = self.directory / (record["generation"] + ".tar.gz")
                local = Path(temporary) / "batch.tar.gz"
                shutil.copyfile(remote, local)
                if file_hash(local) != record["archive_sha256"]:
                    raise ValueError("Backup archive checksum mismatch")
                self._verify_archive(local, staging)
                if file_hash(staging / "shard/_checkpoint/state.json") != record["checkpoint_sha256"]:
                    raise ValueError("Backup checkpoint checksum mismatch")
                local.unlink()
            if target.exists():
                target.rmdir()
            staging.rename(target)
        return True


def prepare_local_workspace(workspace, backup_dir, legacy_raw, legacy_shard):
    """Import an existing Drive layout once, or restore a committed archive chain."""
    workspace = Path(workspace).resolve()
    raw, shard = workspace / "raw", workspace / "shard"
    store = CheckpointBackup(raw, shard, backup_dir)
    if (shard / "_checkpoint/state.json").exists():
        return {"source": "local", **store.summary()}
    if workspace.exists() and any(workspace.iterdir()):
        raise FileExistsError("Local workspace is incomplete; preserve it and select a new local directory")
    if store.restore(workspace):
        return {"source": "drive_backup", **store.summary()}
    workspace.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".import-", dir=workspace.parent) as temporary:
        staging = Path(temporary) / "workspace"
        for source, name in ((Path(legacy_raw), "raw"), (Path(legacy_shard), "shard")):
            target = staging / name
            target.mkdir(parents=True)
            for path in walk(source):
                destination = target / path.relative_to(source)
                if path.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
                    if file_hash(path) != file_hash(destination):
                        raise OSError("Legacy Drive copy checksum mismatch")
        if workspace.exists():
            workspace.rmdir()
        staging.rename(workspace)
    return {"source": "legacy_drive", **store.summary()}
