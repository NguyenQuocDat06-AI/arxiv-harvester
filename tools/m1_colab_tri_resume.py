"""Colab CPU-only Milestone 1 --resume runner for TRI (24120470).

Must execute strictly inside Google Colab CPU-only runtime without copying
local .env files or secrets (e.g., S2_API_KEY) to Colab.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

_RUNNER_CANDIDATES = ["/content", "tools"]
if "__file__" in globals():
    _RUNNER_CANDIDATES.insert(0, str(Path(__file__).resolve().parent))
for _cand in _RUNNER_CANDIDATES:
    if (Path(_cand) / "m2_colab_runner.py").is_file() and _cand not in sys.path:
        sys.path.insert(0, _cand)

import m2_colab_runner as runner  # noqa: E402


def assert_colab_cpu_only() -> None:
    if "COLAB_RELEASE_TAG" not in os.environ:
        raise RuntimeError("M1 TRI resume must run inside Google Colab (COLAB_RELEASE_TAG is not set)")
    if Path("/dev/nvidia0").exists() or os.environ.get("COLAB_TPU_ADDR"):
        raise RuntimeError("M1 TRI resume requires a CPU-only Colab runtime (GPU/TPU detected)")


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        runner.atomic_copy(src, dst)


def seed_mutable_backup(base_backup_dir: Path, resume_backup_dir: Path, drive_delta_dir: Path) -> set[str]:
    orig_files = {
        p.name for p in base_backup_dir.iterdir()
        if p.is_file() and p.name != "HEAD.json" and not p.name.endswith(".tmp")
    }
    resume_backup_dir.mkdir(parents=True, exist_ok=True)
    for fname in sorted(orig_files):
        _link_or_copy(base_backup_dir / fname, resume_backup_dir / fname)

    if not (resume_backup_dir / "HEAD.json").is_file():
        runner.atomic_copy(base_backup_dir / "HEAD.json", resume_backup_dir / "HEAD.json")

    if (drive_delta_dir / "HEAD.json").is_file():
        delta_files = [
            p for p in sorted(drive_delta_dir.iterdir())
            if p.is_file() and p.name != "HEAD.json" and not p.name.endswith(".tmp")
        ]
        for p in delta_files:
            target = resume_backup_dir / p.name
            if not target.is_file() or runner.sha256_file(target) != runner.sha256_file(p):
                runner.atomic_copy(p, target)
        runner.atomic_copy(drive_delta_dir / "HEAD.json", resume_backup_dir / "HEAD.json")
        print(f"[m1-tri] Applied {len(delta_files)} existing Drive backup delta files", flush=True)
    return orig_files


def sync_backup_delta(
    resume_backup_dir: Path,
    drive_delta_dir: Path,
    orig_files: set[str],
    synced_hashes: dict[str, str],
) -> int:
    drive_delta_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in sorted(resume_backup_dir.iterdir()):
        if not p.is_file() or p.name in orig_files or p.name == "HEAD.json" or p.name.endswith(".tmp"):
            continue
        digest = runner.sha256_file(p)
        dst = drive_delta_dir / p.name
        if synced_hashes.get(p.name) != digest or not dst.is_file():
            synced_hashes[p.name] = runner.atomic_copy(p, dst)
            copied += 1
    head_src = resume_backup_dir / "HEAD.json"
    if head_src.is_file():
        head_digest = runner.sha256_file(head_src)
        head_dst = drive_delta_dir / "HEAD.json"
        if synced_hashes.get("HEAD.json") != head_digest or not head_dst.is_file():
            synced_hashes["HEAD.json"] = runner.atomic_copy(head_src, head_dst)
    return copied


def main() -> None:
    assert_colab_cpu_only()
    cfg_path = Path(os.environ.get("M1_TRI_CONFIG", "/content/m1_tri_resume_config.json"))
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    if cfg.get("require_drive_mount", True) and not Path("/content/drive/MyDrive").is_dir():
        raise RuntimeError("Google Drive must be mounted at /content/drive/MyDrive before TRI M1 resume")

    mssv = cfg.get("member_id", "24120470")
    orig_generation = cfg["generation"]
    work_dir = Path(cfg.get("work_dir", "/content/m1_tri_resume/work"))
    raw_dir = work_dir / "raw"
    shard_dir = work_dir / "shard"
    course_export_dir = work_dir / "course_export"
    audit_dir = work_dir / "audit"
    rate_state_dir = work_dir.parent / "rate_state"
    resume_backup_dir = Path(cfg.get("working_backup_dir", "/content/m1_tri_resume/backups/24120470"))
    drive_out_dir = Path(cfg.get("drive_output_dir", "/content/drive/MyDrive/arxiv-harvester-m2/m1_resume_24120470"))
    drive_delta_dir = drive_out_dir / "backup_delta"

    free_gb = shutil.disk_usage("/content").free / 1024**3
    print(
        f"[m1-tri] Start member={mssv} orig_gen={orig_generation} free_disk_gb={free_gb:.2f} "
        f"cpu_count={os.cpu_count()} COLAB_RELEASE_TAG={os.environ.get('COLAB_RELEASE_TAG')} "
        f"s2_key_present={bool(os.environ.get('S2_API_KEY'))}",
        flush=True,
    )
    if not (shard_dir / "_checkpoint/state.json").is_file() and free_gb < float(cfg.get("min_content_free_gb", 20.0)):
        raise OSError(f"Insufficient free disk on /content for TRI restore+resume: {free_gb:.2f} GiB")

    source_root, source_manifest = runner.install_bundle(cfg["bundle_path"], "/content/m2_source", cfg["bundle_sha256"])
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
    import pyarrow.parquet as pq

    base_backup_dir, backup_source = runner.ensure_backup_dir(cfg)
    head_base = json.loads((base_backup_dir / "HEAD.json").read_text(encoding="utf-8"))
    if head_base.get("generation") != orig_generation:
        raise ValueError(f"Base HEAD mismatch: expected {orig_generation}, got {head_base.get('generation')}")
    if cfg.get("head_sha256") and head_base.get("sha256") != cfg["head_sha256"]:
        raise ValueError(f"Base HEAD sha256 mismatch: expected {cfg['head_sha256']}, got {head_base.get('sha256')}")

    orig_files = seed_mutable_backup(base_backup_dir, resume_backup_dir, drive_delta_dir)

    restore_sec = 0.0
    restore_reused = False
    if (shard_dir / "_checkpoint/state.json").is_file():
        state_existing = json.loads((shard_dir / "_checkpoint/state.json").read_text(encoding="utf-8"))
        if state_existing.get("member_id") == mssv:
            restore_reused = True
            print(f"[m1-tri] Reusing existing local TRI workspace at {work_dir} (done_ids={len(state_existing.get('done_ids') or [])})", flush=True)
    if not restore_reused:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        t_res = time.perf_counter()
        cb = CheckpointBackup(raw_dir, shard_dir, resume_backup_dir)
        ok = cb.restore(work_dir)
        restore_sec = time.perf_counter() - t_res
        if not ok:
            raise RuntimeError("CheckpointBackup.restore() returned False for TRI")
        print(f"[m1-tri] Restored TRI backup in {restore_sec:.2f}s via {backup_source}", flush=True)

    drive_out_dir.mkdir(parents=True, exist_ok=True)
    synced_hashes: dict[str, str] = {}
    sync_lock = threading.Lock()
    stop_sync = threading.Event()
    sync_interval = float(cfg.get("sync_interval_sec", 120.0))

    def _safe_sync() -> int:
        with sync_lock:
            return sync_backup_delta(resume_backup_dir, drive_delta_dir, orig_files, synced_hashes)

    def _sync_worker() -> None:
        while not stop_sync.wait(sync_interval):
            try:
                copied = _safe_sync()
                if copied:
                    print(f"[m1-tri] Synced {copied} backup delta files to Drive", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[m1-tri] Periodic Drive delta sync warning: {exc}", flush=True)

    sync_thread = threading.Thread(target=_sync_worker, daemon=True)
    sync_thread.start()

    crawler_cmd = [
        sys.executable,
        "-u",
        "-m",
        "src.crawler.main",
        "--member-id", mssv,
        "--start-month", cfg.get("start_month", "2024-06"),
        "--start-id", str(cfg.get("start_id", 17938)),
        "--end-month", cfg.get("end_month", "2024-07"),
        "--end-id", str(cfg.get("end_id", 2838)),
        "--raw-dir", str(raw_dir),
        "--output-dir", str(shard_dir),
        "--backup-dir", str(resume_backup_dir),
        "--rate-state-dir", str(rate_state_dir),
        "--course-export-dir", str(course_export_dir),
        "--resume",
        "--export-course",
        "--batch-size", str(int(cfg.get("batch_size", 50))),
        "--rate-limit-sec", str(float(cfg.get("rate_limit_sec", 3.0))),
        "--source-rate-limit-sec", str(float(cfg.get("source_rate_limit_sec", 3.0))),
        "--s2-rate-limit-sec", str(float(cfg.get("s2_rate_limit_sec", 5.0))),
        "--s2-batch-size", str(int(cfg.get("s2_batch_size", 50))),
        "--s2-max-attempts", str(int(cfg.get("s2_max_attempts", 1))),
        "--s2-cooldown-sec", str(float(cfg.get("s2_cooldown_sec", 60.0))),
        "--s2-background-retries", str(int(cfg.get("s2_background_retries", 6))),
        "--s2-drain-budget-sec", str(float(cfg.get("s2_drain_budget_sec", 1200.0))),
        "--run-budget-sec", str(float(cfg.get("run_budget_sec", 14400.0))),
        "--checkpoint-every-papers", str(int(cfg.get("checkpoint_every_papers", 25))),
        "--backup-every-papers", str(int(cfg.get("backup_every_papers", 25))),
        "--max-inflight-papers", str(int(cfg.get("max_inflight_papers", 25))),
        "--auto-resume-rate-limit",
        "--recheck-missing",
    ]
    if cfg.get("recheck_bib_fallback"):
        crawler_cmd.append("--recheck-bib-fallback")

    log_path = work_dir / "crawler_resume.log"
    t_crawl = time.perf_counter()
    exit_code = -1
    try:
        with log_path.open("w", encoding="utf-8") as log_f:
            proc = subprocess.Popen(crawler_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            assert proc.stdout is not None
            for line in proc.stdout:
                print(line, end="", flush=True)
                log_f.write(line)
                log_f.flush()
            exit_code = proc.wait()
    finally:
        stop_sync.set()
        sync_thread.join(timeout=30)
        _safe_sync()
        if log_path.is_file():
            runner.atomic_copy(log_path, drive_out_dir / "crawler_resume.log")

    crawl_wall_sec = time.perf_counter() - t_crawl
    if exit_code != 0:
        raise RuntimeError(f"TRI M1 crawler resume failed with exit code {exit_code}")

    # Ensure materialized tables match checkpoint and export_course is up to date.
    state_final = json.loads((shard_dir / "_checkpoint/state.json").read_text(encoding="utf-8"))
    done_ids_count = len(state_final.get("done_ids") or [])
    pub_parquet = shard_dir / "publications.parquet"
    ref_parquet = shard_dir / "references.parquet"
    if (
        not pub_parquet.is_file()
        or not ref_parquet.is_file()
        or pq.ParquetFile(pub_parquet).metadata.num_rows != done_ids_count
    ):
        cp = Checkpoint(str(shard_dir))
        cp.load(state_final["member_id"], state_final["id_range"], backup_legacy=False)
        pubs_map, refs_map, obs_map = _materialize(cp)
        save_publications_parquet([pubs_map[k] for k in sorted(pubs_map)], str(pub_parquet))
        save_references_parquet([r for k in sorted(refs_map) for r in refs_map[k]], str(ref_parquet))
        save_observations([obs_map[k] for k in sorted(obs_map)], str(shard_dir / "crawl_status.parquet"))
        export_to_course_spec(str(shard_dir), str(course_export_dir))

    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_parquet = audit_dir / "source_audit.parquet"
    subprocess.run(
        [
            sys.executable,
            "-u",
            "-m",
            "src.crawler.validate_sources",
            "--publications", str(pub_parquet),
            "--raw-dir", str(raw_dir),
            "--output", str(audit_parquet),
        ],
        check=True,
    )

    # Final sync of shard outputs, course export, audit, logs, and delta chain to Drive.
    _safe_sync()
    synced_files: dict[str, str] = {}
    for src, rel in (
        (shard_dir / "stats.json", "shard_stats.json"),
        (pub_parquet, "shard/publications.parquet"),
        (ref_parquet, "shard/references.parquet"),
        (shard_dir / "crawl_status.parquet", "shard/crawl_status.parquet"),
        (course_export_dir / "papers.parquet", "course_export/papers.parquet"),
        (course_export_dir / "references.parquet", "course_export/references.parquet"),
        (audit_dir / "source_audit.json", "audit/source_audit.json"),
        (audit_dir / "source_audit.retry.jsonl", "audit/source_audit.retry.jsonl"),
        (audit_parquet, "audit/source_audit.parquet"),
        (log_path, "crawler_resume.log"),
    ):
        if src.is_file():
            synced_files[rel] = runner.atomic_copy(src, drive_out_dir / rel)

    shard_stats = json.loads((shard_dir / "stats.json").read_text(encoding="utf-8"))
    new_head = json.loads((resume_backup_dir / "HEAD.json").read_text(encoding="utf-8"))
    audit_summary = json.loads((audit_dir / "source_audit.json").read_text(encoding="utf-8"))
    delta_gens = sorted(
        p.stem for p in resume_backup_dir.iterdir()
        if p.is_file() and p.suffix == ".json" and p.name != "HEAD.json" and p.name not in orig_files
    )

    summary = {
        "member_id": mssv,
        "short_name": "TRI",
        "executed_on": "google_colab_cpu_only",
        "colab_release_tag": os.environ.get("COLAB_RELEASE_TAG"),
        "source_snapshot_sha256": source_manifest.get("source_snapshot_sha256"),
        "orig_generation": orig_generation,
        "new_generation": new_head.get("generation"),
        "new_head_sha256": new_head.get("sha256"),
        "delta_generations_added": delta_gens,
        "restore_reused": restore_reused,
        "restore_source": backup_source,
        "restore_wall_sec": restore_sec,
        "crawl_wall_sec": crawl_wall_sec,
        "crawler_status": shard_stats.get("status"),
        "checkpoint_done_ids": done_ids_count,
        "publications_rows": pq.ParquetFile(pub_parquet).metadata.num_rows,
        "references_rows": pq.ParquetFile(ref_parquet).metadata.num_rows,
        "course_papers_rows": pq.ParquetFile(course_export_dir / "papers.parquet").metadata.num_rows,
        "course_references_rows": pq.ParquetFile(course_export_dir / "references.parquet").metadata.num_rows,
        "source_audit": audit_summary,
        "crawler_environment": shard_stats.get("environment"),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "synced_files": synced_files,
    }
    runner.atomic_write_json(work_dir / "resume_summary.json", summary)
    runner.atomic_copy(work_dir / "resume_summary.json", drive_out_dir / "resume_summary.json")

    print(
        f"[m1-tri] DONE gen={new_head.get('generation')} done_ids={done_ids_count} "
        f"crawler_status={shard_stats.get('status')} crawl_wall_sec={crawl_wall_sec:.2f} "
        f"audit_reasons={audit_summary.get('reasons')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
