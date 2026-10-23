"""Kiểm thử CLI, checkpoint/--resume và profiler. Phụ trách: Trịnh Vỹ Triết (24120474).

Các module của thành viên khác được thay bằng hàm giả để kiểm thử độc lập.
"""

import json
import os
import time

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.crawler import main as cli
from src.crawler.profiler import ResourceProfiler, dir_size_bytes

BASE_ARGS = [
    "--member-id", "24120474",
    "--start-month", "2024-06", "--start-id", "12938",
    "--end-month", "2024-06", "--end-id", "12947",
]


# ---------- parse_args ----------

def test_parse_args_defaults():
    args = cli.parse_args(BASE_ARGS)
    assert args.start_month == "2024-06" and args.end_month == "2024-06"
    assert args.start_id == 12938 and args.end_id == 12947
    assert args.output_dir == os.path.join("data", "shards", "24120474")
    assert args.batch_size == 50 and args.rate_limit_sec == 3.0
    assert args.resume is False


def test_parse_args_accepts_yymm_and_resume():
    args = cli.parse_args([
        "--member-id", "24120282", "--start-month", "2412", "--start-id", "18848",
        "--end-month", "2501", "--end-id", "2641", "--resume", "--batch-size", "100",
    ])
    assert (args.start_month, args.end_month) == ("2024-12", "2025-01")
    assert args.resume and args.batch_size == 100


@pytest.mark.parametrize("override", [
    ["--member-id", "abc"],
    ["--start-id", "0"],
    ["--start-id", "-5"],
    ["--start-month", "2024-13"],
    ["--start-month", "24-06"],
    ["--end-id", "100000"],
    ["--end-id", "12000"],          # kết thúc trước bắt đầu
    ["--end-month", "2024-05"],
    ["--batch-size", "0"],
    ["--rate-limit-sec", "-1"],
])
def test_parse_args_rejects_invalid(override):
    flag, value = override
    argv = list(BASE_ARGS)
    if flag in argv:
        argv[argv.index(flag) + 1] = value
    else:
        argv += override
    with pytest.raises(SystemExit):
        cli.parse_args(argv)


def test_parse_args_requires_all_range_flags():
    with pytest.raises(SystemExit):
        cli.parse_args(BASE_ARGS[:-2])


# ---------- profiler ----------

def test_profiler_exports_stats(tmp_path):
    watched = tmp_path / "watched"
    watched.mkdir()
    (watched / "a.txt").write_bytes(b"x" * 100)
    profiler = ResourceProfiler(sample_interval_sec=0.01, watch_dirs={"w": str(watched)})
    profiler.start()
    with profiler.phase("work"):
        buffer = bytearray(20 * 1024 * 1024)
        time.sleep(0.1)
    with profiler.phase("work"):
        pass
    (watched / "b.txt").write_bytes(b"y" * 50)
    out = tmp_path / "stats.json"
    stats = profiler.stop_and_export(str(out), extra={"member_id": "24120474"})
    del buffer

    assert json.loads(out.read_text(encoding="utf-8")) == stats
    assert stats["member_id"] == "24120474"
    assert stats["phases"]["work"]["calls"] == 2
    assert stats["phases"]["work"]["elapsed_sec"] >= 0.1
    assert stats["runtime_sec"] >= stats["phases"]["work"]["elapsed_sec"]
    mem = stats["memory"]
    assert mem["num_samples"] >= 3
    assert mem["peak_rss_mb"] >= mem["avg_rss_mb"] > 0
    assert mem["bytes_per_mb"] == 1024**2
    assert stats["disk"]["dirs"]["w"] == {"path": str(watched), "before_bytes": 100, "after_bytes": 150}
    assert "python_version" in stats["environment"]


def test_profiler_stop_is_idempotent_and_requires_start(tmp_path):
    profiler = ResourceProfiler(sample_interval_sec=0.01)
    with pytest.raises(RuntimeError):
        profiler.stop_and_export(str(tmp_path / "s.json"))
    profiler.start()
    first = profiler.stop_and_export(str(tmp_path / "s.json"))
    second = profiler.stop_and_export(str(tmp_path / "s.json"), extra={"status": "x"})
    assert first["runtime_sec"] == second["runtime_sec"]
    assert second["status"] == "x"


def test_phase_records_time_on_error():
    profiler = ResourceProfiler()
    with pytest.raises(ValueError):
        with profiler.phase("boom"):
            raise ValueError
    assert profiler._phase_calls["boom"] == 1


def test_dir_size_bytes_missing_dir(tmp_path):
    assert dir_size_bytes(str(tmp_path / "missing")) == 0
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f").write_bytes(b"1234")
    assert dir_size_bytes(str(tmp_path)) == 4


# ---------- pipeline với module giả ----------

class FakeModules:
    """Thay discovery/download/references/storage bằng hàm giả có thể cấu hình lỗi."""

    def __init__(self, monkeypatch, missing=(), fail_download=(), crash_on_batch=None):
        self.missing = set(missing)
        self.fail_download = set(fail_download)
        self.crash_on_batch = crash_on_batch
        self.discovery_calls = 0
        self.downloaded: list[str] = []
        monkeypatch.setattr(cli, "iter_assigned_arxiv_ids", self.iter_ids)
        monkeypatch.setattr(cli, "discover_metadata_batch", self.discover)
        monkeypatch.setattr(cli, "download_and_clean_source", self.download)
        monkeypatch.setattr(cli, "scrape_references_for_paper", self.references)
        monkeypatch.setattr(cli, "save_publications_parquet", self.save)
        monkeypatch.setattr(cli, "save_references_parquet", self.save)

    @staticmethod
    def iter_ids(start_month, start_id, end_month, end_id):
        yymm = start_month[2:4] + start_month[5:7]
        for seq in range(start_id, end_id + 1):
            yield f"{yymm}.{seq:05d}"

    def discover(self, arxiv_ids, rate_limit_sec=3.0):
        self.discovery_calls += 1
        if self.crash_on_batch == self.discovery_calls:
            raise KeyboardInterrupt
        return [{"id": f"{i}v1", "title": f"Paper {i}"} for i in arxiv_ids if i not in self.missing]

    def download(self, arxiv_id, sources_dir, unzipped_dir, rate_limit_sec=3.0, remove_archive=True):
        self.downloaded.append(arxiv_id)
        if arxiv_id in self.fail_download:
            raise ConnectionError("timeout")
        return {"arxiv_id": arxiv_id, "status": "ok", "size_before_bytes": 10, "size_after_bytes": 4, "elapsed_sec": 0.0}

    @staticmethod
    def references(arxiv_id, unzipped_paper_dir=None, rate_limit_sec=3.1):
        return [{"source_id": arxiv_id, "ref": f"{arxiv_id}-r{k}"} for k in range(2)]

    @staticmethod
    def save(records, output_path):
        pq.write_table(pa.Table.from_pylist(records), output_path)


def run_main(tmp_path, *extra):
    cli.main(BASE_ARGS + [
        "--output-dir", str(tmp_path / "shard"),
        "--raw-dir", str(tmp_path / "raw"),
        "--batch-size", "4",
        "--rate-limit-sec", "0",
        "--profile-interval-sec", "0.01",
        *extra,
    ])
    shard = tmp_path / "shard"
    return (
        pq.read_table(shard / "publications.parquet").to_pylist(),
        pq.read_table(shard / "references.parquet").to_pylist(),
        json.loads((shard / "stats.json").read_text(encoding="utf-8")),
    )


def test_full_run(tmp_path, monkeypatch):
    fake = FakeModules(monkeypatch, missing={"2406.12940"}, fail_download={"2406.12945"})
    pubs, refs, stats = run_main(tmp_path)

    assert fake.discovery_calls == 3  # 10 ID, lô 4
    assert len(pubs) == 8 and len(refs) == 16
    assert [p["id"] for p in pubs] == sorted(p["id"] for p in pubs)
    assert stats["status"] == "completed" and stats["is_mock"] is False
    r = stats["results"]
    assert (r["total_ids"], r["succeeded"], r["failed"], r["not_found"]) == (10, 8, 1, 1)
    assert list(r["failed_ids"]) == ["2406.12945"]
    assert r["source_size_before_bytes"] == 80 and r["source_size_after_bytes"] == 32
    assert {"id_generation", "discovery", "download_clean", "references", "storage"} <= set(stats["phases"])


def test_rerun_without_resume_is_refused(tmp_path, monkeypatch):
    FakeModules(monkeypatch)
    run_main(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_main(tmp_path)
    assert exc.value.code == 2


def test_resume_after_interrupt_skips_finished(tmp_path, monkeypatch):
    fake = FakeModules(monkeypatch, fail_download={"2406.12939"}, crash_on_batch=2)
    with pytest.raises(KeyboardInterrupt):
        run_main(tmp_path)
    stats = json.loads((tmp_path / "shard" / "stats.json").read_text(encoding="utf-8"))
    assert stats["status"] == "interrupted" and "KeyboardInterrupt" in stats["error"]

    fake2 = FakeModules(monkeypatch)
    pubs, refs, stats = run_main(tmp_path, "--resume")
    # Lô 1 đã xong 3 bài; bài lỗi 12939 được thử lại cùng 6 ID còn lại.
    assert sorted(fake2.downloaded) == ["2406.12939"] + [f"2406.{n}" for n in range(12942, 12948)]
    assert len(pubs) == 10 and len({p["id"] for p in pubs}) == 10
    assert len(refs) == 20
    assert stats["resumed"] is True and stats["results"]["failed"] == 0


def test_resume_rejects_other_range(tmp_path, monkeypatch):
    FakeModules(monkeypatch, crash_on_batch=1)
    with pytest.raises(KeyboardInterrupt):
        run_main(tmp_path)
    FakeModules(monkeypatch)
    with pytest.raises(SystemExit):
        cli.main([
            "--member-id", "24120474", "--start-month", "2024-06", "--start-id", "1",
            "--end-month", "2024-06", "--end-id", "5", "--resume",
            "--output-dir", str(tmp_path / "shard"), "--raw-dir", str(tmp_path / "raw"),
        ])


def test_not_implemented_module_stops_run(tmp_path, monkeypatch):
    fake = FakeModules(monkeypatch)

    def not_ready(*args, **kwargs):
        raise NotImplementedError("TODO")

    monkeypatch.setattr(cli, "download_and_clean_source", not_ready)
    with pytest.raises(NotImplementedError):
        run_main(tmp_path)
    stats = json.loads((tmp_path / "shard" / "stats.json").read_text(encoding="utf-8"))
    assert stats["status"] == "failed"
    assert fake.discovery_calls == 1
