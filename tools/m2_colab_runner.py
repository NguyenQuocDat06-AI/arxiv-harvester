"""Colab CPU-only orchestrator for Milestone 2 restore, audit, pilot, full, and resume."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile


def allowed_path(name: str) -> bool:
    path = Path(name)
    return (
        path.as_posix() == name
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
        and ":" not in name
        and (
            name in {"pyproject.toml", "requirements.txt", "README.md", "LICENSE"}
            or (name.startswith("src/") and name.endswith(".py"))
            or (name.startswith("configs/") and path.suffix in {".json", ".md"})
        )
    )


def install_bundle(archive_path: str | Path, target_root: str | Path, expected_sha256: str) -> tuple[Path, dict]:
    archive_path, target_root = Path(archive_path), Path(target_root).resolve()
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if not expected_sha256 or digest != expected_sha256:
        raise ValueError(f"Bundle SHA-256 mismatch: expected {expected_sha256}, got {digest}")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [row.filename for row in entries]
        if len(names) != len(set(names)) or len(names) > 150 or sum(row.file_size for row in entries) > 8 * 1024**2:
            raise ValueError("Invalid bundle structure or size")
        manifest = json.loads(archive.read("bundle_manifest.json"))
        if manifest.get("format_version") != 1 or manifest.get("runtime_protocol") != 1:
            raise ValueError("Unsupported bundle runtime protocol")
        if set(names) != set(manifest["files"]) | {"bundle_manifest.json"}:
            raise ValueError("Bundle file list does not match manifest")
        for row in entries:
            if row.filename != "bundle_manifest.json" and not allowed_path(row.filename):
                raise ValueError("File outside source allowlist: " + row.filename)
            if stat.S_ISLNK(row.external_attr >> 16) or row.flag_bits & 1:
                raise ValueError("Bundle contains symlink or encrypted entry")
        contents = {name: archive.read(name) for name in names}
        for name, expected in manifest["files"].items():
            if hashlib.sha256(contents[name]).hexdigest() != expected:
                raise ValueError("Bundle member SHA-256 mismatch: " + name)
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / digest[:16]
    if destination.exists():
        if destination.is_symlink() or not destination.resolve().is_relative_to(target_root):
            raise ValueError("Runtime source path escapes target root")
        expected_python = {name for name in manifest["files"] if name.startswith("src/") and name.endswith(".py")}
        actual_python = {p.relative_to(destination).as_posix() for p in (destination / "src").rglob("*.py")}
        if actual_python != expected_python:
            raise ValueError("Existing runtime source contains unexpected Python files")
        if any(
            not (destination / name).is_file()
            or (destination / name).is_symlink()
            or hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected
            for name, expected in manifest["files"].items()
        ):
            raise ValueError("Installed source differs from bundle; use a clean source folder")
    else:
        with tempfile.TemporaryDirectory(prefix=".source-", dir=target_root) as temporary:
            staging = Path(temporary).resolve()
            unpacked = staging / "runtime"
            for name, data in contents.items():
                target = unpacked / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            unpacked.rename(destination)
    return destination, manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(src)
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        shutil.copyfile(src, tmp)
        if sha256_file(tmp) != digest:
            raise OSError(f"Copy checksum mismatch for {dst}")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return digest


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def download_drive_file(file_id: str, dest: Path, expected_sha256: str | None = None, retries: int = 5) -> None:
    if dest.is_file() and expected_sha256 is not None and sha256_file(dest) == expected_sha256:
        return
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) arxiv-harvester-m2-runner/1.0"}
    last_err: Exception | None = None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            if expected_sha256 is not None and sha256_file(tmp) != expected_sha256:
                raise ValueError(f"Checksum mismatch for downloaded {dest.name} (file_id={file_id})")
            os.replace(tmp, dest)
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            tmp.unlink(missing_ok=True)
            time.sleep(min(15.0, 1.0 * (2**attempt)))
    raise RuntimeError(f"Failed downloading {dest.name} ({file_id}): {last_err}")


def ensure_backup_dir(cfg: dict) -> tuple[Path, str]:
    drive_dir = cfg.get("drive_backup_dir")
    if drive_dir and (Path(drive_dir) / "HEAD.json").is_file():
        return Path(drive_dir), "drive_mount"
    chain_path = Path(cfg["chain_manifest_path"])
    if not chain_path.is_file():
        raise FileNotFoundError(f"Neither drive_backup_dir ({drive_dir}) nor chain_manifest_path ({chain_path}) is available")
    chain = json.loads(chain_path.read_text(encoding="utf-8"))
    mssv = cfg["member_id"]
    generation = cfg["generation"]
    local_backup = Path(f"/content/m2_backups/{mssv}/{generation}")
    local_backup.mkdir(parents=True, exist_ok=True)
    head_path = local_backup / "HEAD.json"
    if not head_path.is_file() or json.loads(head_path.read_text(encoding="utf-8")).get("generation") != generation:
        download_drive_file(chain["head_file_id"], head_path)
    items = chain["oldest_to_newest"]
    print(f"[runner] Downloading {len(items)} verified backup generations for {mssv}...", flush=True)
    t0 = time.perf_counter()

    def _fetch_one(item: dict) -> str:
        gen = item["generation"]
        download_drive_file(item["receipt_file_id"], local_backup / f"{gen}.json", item["receipt_sha256"])
        download_drive_file(item["archive_file_id"], local_backup / f"{gen}.tar.gz", item["archive_sha256"])
        return gen

    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_fetch_one, item) for item in items]
        for fut in as_completed(futures):
            fut.result()
            done += 1
            if done % 50 == 0 or done == len(items):
                print(f"[runner] Backup download progress: {done}/{len(items)} ({time.perf_counter() - t0:.1f}s)", flush=True)
    return local_backup, "public_chain_download"


def select_stratified_pilot(pub_path: Path, audit_path: Path, target_size: int, seed: int, out_dir: Path) -> tuple[Path, Path, Path]:
    import pyarrow as pa
    import pyarrow.parquet as pq
    from src.crawler.storage import PUBLICATIONS_SCHEMA, export_to_course_spec, save_publications_parquet, save_references_parquet

    pubs = {row["id"]: row for row in pq.ParquetFile(pub_path).read().to_pylist()}
    audit_rows = pq.ParquetFile(audit_path).read().to_pylist()
    by_paper: dict[str, list[dict]] = {}
    for row in audit_rows:
        by_paper.setdefault(row["arxiv_id"], []).append(row)

    features = {}
    for pid, p in pubs.items():
        arows = by_paper.get(pid, [])
        features[pid] = {
            "num_versions": len(p.get("versions") or []),
            "max_tex_files": max((r.get("tex_files") or 0 for r in arows), default=0),
            "total_bbl_files": sum((r.get("bbl_files") or 0 for r in arows)),
            "total_actual_bytes": sum((r.get("actual_size_bytes") or 0 for r in arows)),
            "has_empty_no_tex": any(r.get("source_status") in {"pdf_only", "no_latex"} for r in arows),
            "has_not_found": any(r.get("source_status") == "not_found" for r in arows),
            "has_unverified": any(not r.get("verified") for r in arows),
        }

    selected: list[str] = []
    selected_set: set[str] = set()
    buckets: dict[str, list[str]] = {}

    def pick(bucket_name: str, candidates: list[str], quota: int) -> None:
        chosen = []
        for pid in candidates:
            if len(selected) >= target_size or len(chosen) >= quota:
                break
            if pid not in selected_set:
                selected_set.add(pid)
                selected.append(pid)
                chosen.append(pid)
        buckets[bucket_name] = chosen

    sorted_ids = sorted(pubs)
    pick("unverified_or_issue", [p for p in sorted_ids if features[p]["has_unverified"]], 15)
    pick("not_found_404", [p for p in sorted_ids if features[p]["has_not_found"]], 15)
    pick("empty_no_tex", [p for p in sorted_ids if features[p]["has_empty_no_tex"]], 25)
    pick("with_bbl", [p for p in sorted_ids if features[p]["total_bbl_files"] > 0], 35)
    pick("multi_version_ge3", [p for p in sorted_ids if features[p]["num_versions"] >= 3], 45)
    pick("multi_version_2", [p for p in sorted_ids if features[p]["num_versions"] == 2], 35)
    pick("multi_file_tex", [p for p in sorted_ids if features[p]["max_tex_files"] >= 3], 40)
    top_by_size = sorted(sorted_ids, key=lambda p: (-features[p]["total_actual_bytes"], p))
    pick("large_tex", top_by_size, 30)

    rng = random.Random(seed)
    remaining = [p for p in sorted_ids if p not in selected_set]
    rng.shuffle(remaining)
    pick("seeded_random_fill", remaining, target_size - len(selected))

    out_dir.mkdir(parents=True, exist_ok=True)
    pilot_pubs = [pubs[pid] for pid in sorted(selected_set)]
    pilot_pub_path = out_dir / "publications.parquet"
    save_publications_parquet(pilot_pubs, str(pilot_pub_path))

    src_ref_path = pub_path.with_name("references.parquet")
    if src_ref_path.is_file():
        refs = [r for r in pq.ParquetFile(src_ref_path).read().to_pylist() if r["arxiv_id"] in selected_set]
    else:
        refs = []
    save_references_parquet(refs, str(out_dir / "references.parquet"))

    pilot_course = out_dir / "course"
    export_to_course_spec(str(out_dir), str(pilot_course))

    selection_info = {
        "method": "stratified_deterministic_pilot",
        "seed": seed,
        "target_size": target_size,
        "selected_publications": len(selected_set),
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
        "selected_ids": sorted(selected_set),
    }
    sel_path = out_dir / "pilot_selection.json"
    atomic_write_json(sel_path, selection_info)
    return pilot_pub_path, pilot_course, sel_path


def sync_output_batches(parsed_dir: Path, drive_mode_dir: Path, archived_keys: set[str], state_obj: dict) -> int:
    checkpoint_file = parsed_dir / "checkpoint.json"
    if not checkpoint_file.is_file():
        return 0
    cp = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    completed = cp.get("completed") or {}
    new_ids = [pid for pid in sorted(completed) if pid not in archived_keys]
    batch_dir = drive_mode_dir / "output_batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    if new_ids:
        state_obj["batch_num"] += 1
        batch_name = f"batch_{state_obj['batch_num']:04d}.tar.gz"
        with tempfile.TemporaryDirectory(prefix=".batch-", dir=parsed_dir.parent) as td:
            local_tar = Path(td) / batch_name
            added_files = []
            with tarfile.open(local_tar, "w:gz", compresslevel=1) as tf:
                for pid in new_ids:
                    for rel in (completed[pid].get("files") or {}):
                        src = parsed_dir / rel
                        if src.is_file():
                            tf.add(src, arcname=rel, recursive=False)
                            added_files.append(rel)
            tar_sha = atomic_copy(local_tar, batch_dir / batch_name)
        state_obj["batches"].append({
            "batch_file": batch_name,
            "sha256": tar_sha,
            "paper_count": len(new_ids),
            "file_count": len(added_files),
        })
        archived_keys.update(new_ids)
        atomic_write_json(batch_dir / "batches_manifest.json", state_obj)
    atomic_copy(checkpoint_file, batch_dir / "checkpoint.json")
    log_file = parsed_dir / "parser.log"
    if log_file.is_file():
        atomic_copy(log_file, drive_mode_dir / "parser.log")
    return len(new_ids)


def restore_output_batches_if_needed(parsed_dir: Path, drive_mode_dir: Path) -> bool:
    if (parsed_dir / "checkpoint.json").is_file():
        return False
    batch_dir = drive_mode_dir / "output_batches"
    manifest_file = batch_dir / "batches_manifest.json"
    cp_file = batch_dir / "checkpoint.json"
    if not manifest_file.is_file() or not cp_file.is_file():
        return False
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    parsed_dir.mkdir(parents=True, exist_ok=True)
    for b in manifest.get("batches", []):
        tar_path = batch_dir / b["batch_file"]
        if sha256_file(tar_path) != b["sha256"]:
            raise ValueError(f"Output batch checksum mismatch: {tar_path}")
        with tarfile.open(tar_path, "r:gz") as tf:
            for member in tf.getmembers():
                dest = (parsed_dir / member.name).resolve()
                if not dest.is_relative_to(parsed_dir.resolve()) or not member.isfile():
                    raise ValueError(f"Unsafe member in output batch: {member.name}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src_f, dest.open("wb") as out_f:
                    shutil.copyfileobj(src_f, out_f)
    atomic_copy(cp_file, parsed_dir / "checkpoint.json")
    return True


def main() -> None:
    cfg_path = Path(os.environ.get("M2_RUN_CONFIG", "/content/m2_run_config.json"))
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    if Path("/dev/nvidia0").exists() or os.environ.get("COLAB_TPU_ADDR"):
        raise RuntimeError("M2 requires a CPU-only Colab runtime (GPU/TPU detected)")

    mssv = cfg["member_id"]
    generation = cfg["generation"]
    mode = cfg["mode"]
    if mode not in {"pilot", "full", "resume"}:
        raise ValueError(f"Unsupported mode: {mode}")

    disk_content = shutil.disk_usage("/content")
    print(
        f"[runner] Start member={mssv} mode={mode} gen={generation} "
        f"python={sys.version.split()[0]} cpu_count={os.cpu_count()} "
        f"free_disk_gb={disk_content.free / 1024**3:.2f} COLAB_RELEASE_TAG={os.environ.get('COLAB_RELEASE_TAG')}",
        flush=True,
    )

    source_root, source_manifest = install_bundle(cfg["bundle_path"], "/content/m2_source", cfg["bundle_sha256"])
    marker = source_root / ".editable_installed"
    if not marker.is_file():
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "-e", str(source_root)], check=True)
        marker.write_text("ok\n", encoding="utf-8")
    os.chdir(source_root)
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    from src.crawler.drive_backup import CheckpointBackup
    from src.crawler.main import Checkpoint, _materialize
    from src.crawler.observations import save_observations
    from src.crawler.storage import export_to_course_spec, save_publications_parquet, save_references_parquet
    from src.crawler.validate_sources import audit_sources, validate_course_tables
    import pyarrow.parquet as pq

    work_dir = Path(f"/content/m2_work/{mssv}/{generation}")
    verify_path = work_dir / ".restore_verified.json"
    restore_sec = 0.0
    restore_reused = False
    restore_source = "existing_local"

    if (
        verify_path.is_file()
        and (work_dir / "shard/_checkpoint/state.json").is_file()
        and json.loads(verify_path.read_text(encoding="utf-8")).get("generation") == generation
        and json.loads(verify_path.read_text(encoding="utf-8")).get("head_sha256") == cfg.get("head_sha256")
    ):
        restore_reused = True
        print(f"[runner] Reusing already-verified restored corpus at {work_dir}", flush=True)
    else:
        if disk_content.free < 15 * 1024**3:
            raise OSError(f"Insufficient free disk on /content before restore: {disk_content.free / 1024**3:.2f} GiB")
        backup_dir, restore_source = ensure_backup_dir(cfg)
        head = json.loads((backup_dir / "HEAD.json").read_text(encoding="utf-8"))
        if head.get("generation") != generation:
            raise ValueError(f"HEAD mismatch: expected {generation}, got {head.get('generation')}")
        if cfg.get("head_sha256") and head.get("sha256") != cfg["head_sha256"]:
            raise ValueError(f"HEAD receipt sha256 mismatch: expected {cfg['head_sha256']}, got {head.get('sha256')}")
        if work_dir.exists():
            shutil.rmtree(work_dir)
        t_res = time.perf_counter()
        cb = CheckpointBackup(work_dir / "raw", work_dir / "shard", backup_dir)
        ok = cb.restore(work_dir)
        restore_sec = time.perf_counter() - t_res
        if not ok:
            raise RuntimeError(f"CheckpointBackup.restore() returned False for {mssv}")
        atomic_write_json(verify_path, {
            "member_id": mssv,
            "generation": generation,
            "head_sha256": head.get("sha256"),
            "restore_source": restore_source,
            "restore_wall_sec": restore_sec,
            "restored_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        print(f"[runner] Restore completed in {restore_sec:.2f}s via {restore_source}", flush=True)

    shard_dir = work_dir / "shard"
    state_json = json.loads((shard_dir / "_checkpoint/state.json").read_text(encoding="utf-8"))
    done_ids_count = len(state_json.get("done_ids") or [])
    pub_parquet = shard_dir / "publications.parquet"
    ref_parquet = shard_dir / "references.parquet"
    materialized_flag = False
    need_materialize = not pub_parquet.is_file() or not ref_parquet.is_file()
    if not need_materialize:
        existing_rows = pq.ParquetFile(pub_parquet).metadata.num_rows
        if existing_rows < done_ids_count:
            need_materialize = True
    if need_materialize:
        cp = Checkpoint(str(shard_dir))
        cp.load(state_json["member_id"], state_json["id_range"], backup_legacy=False)
        pubs_map, refs_map, obs_map = _materialize(cp)
        save_publications_parquet([pubs_map[k] for k in sorted(pubs_map)], str(pub_parquet))
        all_refs = [r for k in sorted(refs_map) for r in refs_map[k]]
        save_references_parquet(all_refs, str(ref_parquet))
        save_observations([obs_map[k] for k in sorted(obs_map)], str(shard_dir / "crawl_status.parquet"))
        materialized_flag = True
        print(f"[runner] Materialized working tables from checkpoint: {len(pubs_map)} pubs, {len(all_refs)} refs", flush=True)

    course_dir = work_dir / "course"
    need_course = not (course_dir / "papers.parquet").is_file() or not (course_dir / "references.parquet").is_file()
    if not need_course:
        c_rows = pq.ParquetFile(course_dir / "papers.parquet").metadata.num_rows
        w_rows = pq.ParquetFile(pub_parquet).metadata.num_rows
        if c_rows != w_rows:
            need_course = True
    if need_course:
        export_to_course_spec(str(shard_dir), str(course_dir))
    course_check = validate_course_tables(str(course_dir))
    if not course_check["valid"]:
        raise RuntimeError(f"Course export invalid for {mssv}: {course_check}")

    audit_dir = work_dir / "audit"
    audit_parquet = audit_dir / "source_audit.parquet"
    audit_json = audit_dir / "source_audit.json"
    audit_sec = 0.0
    if not audit_json.is_file() or not audit_parquet.is_file():
        t_aud = time.perf_counter()
        audit_report = audit_sources(str(pub_parquet), str(work_dir / "raw"), str(audit_parquet))
        audit_sec = time.perf_counter() - t_aud
        print(f"[runner] Source audit finished in {audit_sec:.2f}s: {audit_report['reasons']}", flush=True)
    else:
        audit_report = json.loads(audit_json.read_text(encoding="utf-8"))

    drive_root = Path(cfg.get("drive_output_root", "/content/drive/MyDrive/arxiv-harvester-m2"))
    drive_mode_dir = drive_root / "members" / mssv / generation / ("full" if mode == "resume" else mode)
    drive_mode_dir.mkdir(parents=True, exist_ok=True)

    if mode == "pilot":
        pilot_dir = work_dir / "pilot_input"
        pub_input, course_input, sel_path = select_stratified_pilot(
            pub_parquet,
            audit_parquet,
            int(cfg.get("pilot_size", 250)),
            int(cfg.get("pilot_seed", 20261121)),
            pilot_dir,
        )
        parsed_dir = work_dir / "parsed_pilot"
        if parsed_dir.exists():
            shutil.rmtree(parsed_dir)
    else:
        pub_input, course_input, sel_path = pub_parquet, course_dir, None
        parsed_dir = work_dir / "parsed_full"
        if mode == "full" and cfg.get("fresh_output", True) and parsed_dir.exists():
            shutil.rmtree(parsed_dir)
        elif mode == "resume":
            restored_batches = restore_output_batches_if_needed(parsed_dir, drive_root / "members" / mssv / generation / "full")
            if restored_batches:
                print("[runner] Restored prior output batches from Drive for --resume", flush=True)

    parsed_dir.mkdir(parents=True, exist_ok=True)
    time_bin = "/usr/bin/time" if Path("/usr/bin/time").is_file() else shutil.which("time")
    parser_cmd = [
        sys.executable,
        "-u",
        "-m",
        "src.parser.main",
        "--publications",
        str(pub_input),
        "--raw-dir",
        str(work_dir / "raw"),
        "--output-dir",
        str(parsed_dir),
        "--sample-interval-sec",
        str(cfg.get("sample_interval_sec", 0.5)),
        "--min-free-gb",
        str(cfg.get("min_free_gb", 2.0)),
    ]
    if mode == "resume" and (parsed_dir / "checkpoint.json").is_file():
        parser_cmd.append("--resume")
    if cfg.get("root_overrides_rel"):
        ov_path = source_root / cfg["root_overrides_rel"]
        if ov_path.is_file():
            parser_cmd.extend(["--root-overrides", str(ov_path)])
    command = ([time_bin, "-v", "-o", str(parsed_dir / "time_v.txt"), *parser_cmd]
               if time_bin else parser_cmd)

    run_config_doc = {
        "member_id": mssv,
        "short_name": cfg.get("short_name"),
        "generation": generation,
        "head_sha256": cfg.get("head_sha256"),
        "mode": mode,
        "bundle_sha256": cfg["bundle_sha256"],
        "source_snapshot_sha256": source_manifest.get("source_snapshot_sha256"),
        "source_base_commit": source_manifest.get("source_base_commit"),
        "command": command,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(parsed_dir / "run_configuration.json", run_config_doc)

    archived_keys: set[str] = set()
    batch_state = {"batch_num": 0, "batches": []}
    if mode == "resume":
        old_bm = drive_root / "members" / mssv / generation / "full" / "output_batches" / "batches_manifest.json"
        if old_bm.is_file():
            batch_state = json.loads(old_bm.read_text(encoding="utf-8"))
        cp_existing = parsed_dir / "checkpoint.json"
        if cp_existing.is_file():
            archived_keys.update((json.loads(cp_existing.read_text(encoding="utf-8")).get("completed") or {}).keys())

    stop_sync = threading.Event()
    sync_interval = float(cfg.get("sync_batch_interval_sec", 120.0))
    sync_target = drive_root / "members" / mssv / generation / ("full" if mode == "resume" else mode)

    def _sync_worker() -> None:
        while not stop_sync.wait(sync_interval):
            try:
                sync_output_batches(parsed_dir, sync_target, archived_keys, batch_state)
            except Exception as exc:  # noqa: BLE001
                print(f"[runner] Periodic Drive sync warning: {exc}", flush=True)

    sync_thread = threading.Thread(target=_sync_worker, daemon=True)
    sync_thread.start()

    t_parse = time.perf_counter()
    with (parsed_dir / "parser.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        exit_code = process.wait()
    parser_wall_sec = time.perf_counter() - t_parse
    child_rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
    os_children_peak_rss_kb = int(child_rusage.ru_maxrss)

    stop_sync.set()
    sync_thread.join(timeout=30)
    if exit_code != 0:
        sync_output_batches(parsed_dir, sync_target, archived_keys, batch_state)
        raise RuntimeError(f"Parser failed with exit code {exit_code}")

    t_val = time.perf_counter()
    val_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.parser.validation",
            "--course-dir",
            str(course_input),
            "--parsed-dir",
            str(parsed_dir),
            "--publications",
            str(pub_input),
            "--output",
            str(parsed_dir / "project_validation.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    validate_wall_sec = time.perf_counter() - t_val
    if val_proc.returncode not in (0, 2):
        raise RuntimeError(f"Validation failed ({val_proc.returncode}): {val_proc.stdout}\n{val_proc.stderr}")

    t_sync = time.perf_counter()
    sync_output_batches(parsed_dir, sync_target, archived_keys, batch_state)
    stats = json.loads((parsed_dir / "stats.json").read_text(encoding="utf-8"))
    validation = json.loads((parsed_dir / "project_validation.json").read_text(encoding="utf-8"))

    runner_summary = {
        "member_id": mssv,
        "short_name": cfg.get("short_name"),
        "generation": generation,
        "mode": mode,
        "restore_reused": restore_reused,
        "restore_source": restore_source,
        "restore_wall_sec": restore_sec,
        "materialized_from_checkpoint": materialized_flag,
        "checkpoint_done_ids": done_ids_count,
        "working_publications": pq.ParquetFile(pub_parquet).metadata.num_rows,
        "source_audit_wall_sec": audit_sec,
        "source_audit_summary": audit_report,
        "parser_wall_sec": parser_wall_sec,
        "os_children_peak_rss_kb": os_children_peak_rss_kb,
        "time_binary_used": time_bin,
        "validate_wall_sec": validate_wall_sec,
        "parser_status": stats.get("status"),
        "parser_runtime_sec": stats.get("runtime_sec"),
        "status_counts": stats.get("status_counts"),
        "structural_valid": validation.get("structural_valid"),
        "processing_complete": validation.get("processing_complete"),
        "environment": stats.get("environment"),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(parsed_dir / "runner_summary.json", runner_summary)

    # Sync summary & log artifacts to Drive
    sync_files: dict[str, str] = {}
    for fname in ("stats.json", "manifest.json", "project_validation.json", "time_v.txt", "parser.log", "run_configuration.json", "runner_summary.json"):
        src = parsed_dir / fname
        if src.is_file():
            sync_files[fname] = atomic_copy(src, drive_mode_dir / fname)
    for run_file in sorted((parsed_dir / "runs").glob("*/*")):
        if run_file.name in {"stats.json", "resource_samples.jsonl"} and run_file.is_file():
            rel = run_file.relative_to(parsed_dir).as_posix()
            sync_files[rel] = atomic_copy(run_file, drive_mode_dir / rel)
    if sel_path and sel_path.is_file():
        sync_files["pilot_selection.json"] = atomic_copy(sel_path, drive_mode_dir / "pilot_selection.json")
    member_drive_dir = drive_root / "members" / mssv / generation
    for afname in ("source_audit.json", "source_audit.retry.jsonl", "source_audit.parquet"):
        src = audit_dir / afname
        if src.is_file():
            sync_files[f"audit/{afname}"] = atomic_copy(src, member_drive_dir / "audit" / afname)
    if mode != "pilot":
        for src, rel in (
            (shard_dir / "publications.parquet", "m1_tables/publications.parquet"),
            (shard_dir / "references.parquet", "m1_tables/references.parquet"),
            (shard_dir / "crawl_status.parquet", "m1_tables/crawl_status.parquet"),
            (shard_dir / "stats.json", "m1_tables/stats.json"),
            (course_dir / "papers.parquet", "m1_tables/course/papers.parquet"),
            (course_dir / "references.parquet", "m1_tables/course/references.parquet"),
        ):
            if src.is_file():
                sync_files[rel] = atomic_copy(src, member_drive_dir / rel)
    runner_summary["drive_sync_wall_sec"] = time.perf_counter() - t_sync
    atomic_write_json(parsed_dir / "runner_summary.json", runner_summary)
    sync_files["runner_summary.json"] = atomic_copy(parsed_dir / "runner_summary.json", drive_mode_dir / "runner_summary.json")
    atomic_write_json(drive_mode_dir / "sync_manifest.json", {"files": sync_files, "synced_at_utc": datetime.now(timezone.utc).isoformat()})

    print(
        f"[runner] DONE member={mssv} mode={mode} status={stats.get('status')} "
        f"structural_valid={validation.get('structural_valid')} "
        f"runtime_sec={stats.get('runtime_sec'):.2f} statuses={stats.get('status_counts')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
