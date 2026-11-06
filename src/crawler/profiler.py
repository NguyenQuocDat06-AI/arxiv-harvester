"""Theo dõi tài nguyên. Phụ trách: Trịnh Vỹ Triết (24120474)."""

import json
import os
import platform
import statistics
import sys
import threading
import time
import math
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import psutil

# Quy đổi đơn vị: 1 MB trong stats.json = 1024**2 byte (MiB).
BYTES_PER_MB = 1024**2
_ACTIVE_PROFILER = ContextVar("arxiv_resource_profiler", default=None)


def resource_checkpoint() -> None:
    """Sample disk usage at an operation boundary."""
    profiler = _ACTIVE_PROFILER.get()
    if profiler is not None:
        profiler.capture(disk=True)


def dir_size_bytes(path: str) -> int:
    """Cộng kích thước tệp thường trong cây thư mục, không đi theo symlink."""
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
    return total


def _os_peak_rss_bytes(process: psutil.Process) -> int | None:
    """Peak RSS do hệ điều hành ghi nhận cho cả vòng đời tiến trình."""
    try:
        info = process.memory_info()
        if hasattr(info, "peak_wset"):  # Windows
            return int(info.peak_wset)
        import resource  # Linux/macOS

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux trả KB, macOS trả byte.
        return int(peak) if sys.platform == "darwin" else int(peak) * 1024
    except Exception:
        return None


def _environment() -> dict:
    """Thông tin môi trường chạy để ghi kèm số đo."""
    versions = {}
    for name in ("psutil", "pandas", "pyarrow", "requests", "arxiv"):
        module = sys.modules.get(name)
        if module is not None:
            versions[name] = getattr(module, "__version__", None)
    is_colab = "google.colab" in sys.modules or "COLAB_RELEASE_TAG" in os.environ
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    has_gpu = (visible not in {"", "-1"}) or os.path.exists("/dev/nvidia0")
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "is_google_colab": is_colab,
        "cpu_only": not has_gpu,
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "total_memory_mb": round(psutil.virtual_memory().total / BYTES_PER_MB, 2),
        "library_versions": versions,
    }


class ResourceProfiler:
    """Theo dõi thời gian, RAM và dung lượng đĩa trong lúc chạy pipeline."""

    def __init__(
        self,
        sample_interval_sec: float = 0.5,
        watch_dirs: dict[str, str] | None = None,
        disk_interval_sec: float = 5.0,
        samples_path: str | Path | None = None,
    ) -> None:
        if not math.isfinite(sample_interval_sec) or sample_interval_sec <= 0:
            raise ValueError("sample_interval_sec phải lớn hơn 0")
        if not math.isfinite(disk_interval_sec) or disk_interval_sec <= 0:
            raise ValueError("disk_interval_sec phải lớn hơn 0")
        self.sample_interval_sec = sample_interval_sec
        self.disk_interval_sec = disk_interval_sec
        self.samples_path = Path(samples_path) if samples_path is not None else None
        self._sample_write_error = None
        self._last_disk_sample = None
        self.watch_dirs = dict(watch_dirs or {})
        self._process = psutil.Process()
        self._samples: list[int] = []
        self._sample_times: list[float] = []
        self._disk_samples: list[dict] = []
        self._sampling_lock = threading.Lock()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_perf: float | None = None
        self._end_perf: float | None = None
        self._started_at: str | None = None
        self._phase_sec: dict[str, float] = {}
        self._phase_calls: dict[str, int] = {}
        self._disk_before: dict[str, int] = {}
        self._result: dict | None = None

    def start(self) -> None:
        """Bắt đầu bấm giờ và lấy mẫu bộ nhớ."""
        if self._thread is not None:
            raise RuntimeError("Profiler đã được bắt đầu")
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._disk_before = {
            label: dir_size_bytes(path) for label, path in self.watch_dirs.items()
        }
        self._start_perf = time.perf_counter()
        if self.samples_path is not None:
            self.samples_path.parent.mkdir(parents=True, exist_ok=True)
            with self.samples_path.open("x", encoding="utf-8"):
                pass
        self._sample()
        self._thread = threading.Thread(
            target=self._sampling_loop, name="resource-profiler", daemon=True
        )
        self._thread.start()

    def _sample(self, disk: bool = True) -> None:
        with self._sampling_lock:
            self._sample_unlocked(disk)

    def _sample_unlocked(self, disk: bool = True) -> None:
        try:
            rss = self._process.memory_info().rss
        except psutil.Error:
            return
        try:
            children = self._process.children(recursive=True)
        except psutil.Error:
            children = []
        seen = {self._process.pid}
        for child in children:
            if child.pid in seen:
                continue
            seen.add(child.pid)
            try:
                rss += child.memory_info().rss
            except psutil.Error:
                pass
        timestamp = time.perf_counter()
        sizes = {label: dir_size_bytes(path) for label, path in self.watch_dirs.items()} if disk else {}
        if disk:
            self._last_disk_sample = timestamp
        roots = []
        for label, path in sorted(self.watch_dirs.items(), key=lambda item: len(os.path.abspath(item[1]))):
            absolute = os.path.realpath(path)
            def contained(parent):
                try:
                    return os.path.commonpath([absolute, parent]) == parent
                except ValueError:
                    return False
            if not any(contained(parent) for _, parent in roots):
                roots.append((label, absolute))
        with self._lock:
            self._samples.append(rss)
            self._sample_times.append(timestamp)
            if disk:
                self._disk_samples.append({"elapsed_sec": timestamp - self._start_perf,
                                           "total_bytes": sum(sizes[label] for label, _ in roots), "dirs": sizes})
            if self.samples_path is not None:
                rows = [{"kind": "rss", "elapsed_sec": timestamp - self._start_perf, "rss_bytes": rss}]
                if disk:
                    rows.append({"kind": "disk", **self._disk_samples[-1]})
                try:
                    with self.samples_path.open("a", encoding="utf-8") as stream:
                        for row in rows:
                            stream.write(json.dumps(row) + "\n")
                except OSError as error:
                    self._sample_write_error = repr(error)

    def capture(self, disk: bool = True) -> None:
        if self._start_perf is not None and self._end_perf is None:
            self._sample(disk=disk)

    def _sampling_loop(self) -> None:
        while not self._stop_event.wait(self.sample_interval_sec):
            disk = self._last_disk_sample is None or time.perf_counter() - self._last_disk_sample >= self.disk_interval_sec
            self._sample(disk=disk)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Cộng dồn thời gian của một pha, kể cả khi pha đó ném lỗi."""
        begin = time.perf_counter()
        token = _ACTIVE_PROFILER.set(self)
        try:
            yield
        finally:
            elapsed = time.perf_counter() - begin
            self._phase_sec[name] = self._phase_sec.get(name, 0.0) + elapsed
            self._phase_calls[name] = self._phase_calls.get(name, 0) + 1
            self.capture(disk=False)
            _ACTIVE_PROFILER.reset(token)

    def _stop(self) -> None:
        if self._thread is None:
            raise RuntimeError("Profiler chưa được bắt đầu")
        if self._end_perf is not None:
            return
        self._stop_event.set()
        self._thread.join(timeout=max(5.0, self.sample_interval_sec * 4))
        self._sample()
        self._end_perf = time.perf_counter()

    def stop_and_export(self, output_json_path: str, extra: dict | None = None) -> dict:
        """Dừng đo và ghi stats.json kèm đơn vị."""
        self._stop()
        if self._result is None:
            with self._lock:
                samples = list(self._samples)
                timestamps = list(self._sample_times)
                disk_samples = list(self._disk_samples)
            duration = sum(b - a for a, b in zip(timestamps, timestamps[1:]))
            average = (sum(value * (b - a) for value, a, b in zip(samples, timestamps, timestamps[1:])) / duration
                       if duration else statistics.fmean(samples))
            disk_after = {
                label: dir_size_bytes(path) for label, path in self.watch_dirs.items()
            }
            os_peak = _os_peak_rss_bytes(self._process)
            self._result = {
                "started_at_utc": self._started_at,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "runtime_sec": round(self._end_perf - self._start_perf, 3),
                "phases": {
                    name: {
                        "elapsed_sec": round(sec, 3),
                        "calls": self._phase_calls[name],
                    }
                    for name, sec in self._phase_sec.items()
                },
                "memory": {
                    "metric": "Tổng RSS tiến trình chính và tiến trình con tại cùng thời điểm",
                    "unit": "MB",
                    "bytes_per_mb": BYTES_PER_MB,
                    "peak_rss_mb": round(max(samples) / BYTES_PER_MB, 2),
                    "avg_rss_mb": round(average / BYTES_PER_MB, 2),
                    "average_method": "time_weighted_left_samples",
                    "os_reported_peak_rss_mb": (
                        round(os_peak / BYTES_PER_MB, 2) if os_peak else None
                    ),
                    "num_samples": len(samples),
                    "sample_interval_sec": self.sample_interval_sec,
                },
                "disk": {
                    "unit": "bytes",
                    "peak_bytes": max((s["total_bytes"] for s in disk_samples), default=0),
                    "final_bytes": disk_samples[-1]["total_bytes"] if disk_samples else 0,
                    "method": "periodic samples and operation checkpoints; nested directories counted once",
                    "sample_interval_sec": self.disk_interval_sec,
                    "dirs": {
                        label: {
                            "path": path,
                            "before_bytes": self._disk_before.get(label, 0),
                            "after_bytes": disk_after[label],
                        }
                        for label, path in self.watch_dirs.items()
                    },
                },
                "environment": _environment(),
            }
            samples_path = Path(output_json_path).parent / "resource_samples.jsonl"
            samples_path.parent.mkdir(parents=True, exist_ok=True)
            samples_temporary = samples_path.with_name(samples_path.name + ".tmp")
            with samples_temporary.open("w", encoding="utf-8") as stream:
                for timestamp, rss in zip(timestamps, samples):
                    stream.write(json.dumps({"kind": "rss", "elapsed_sec": timestamp - self._start_perf, "rss_bytes": rss}) + "\n")
                for sample in disk_samples:
                    stream.write(json.dumps({"kind": "disk", **sample}) + "\n")
            samples_temporary.replace(samples_path)
            self._result["samples_file"] = str(samples_path)
        result = {**self._result, **(extra or {})}
        if self._sample_write_error is not None:
            result["sample_log_error"] = self._sample_write_error
        _write_json_atomic(output_json_path, result)
        return result


def _write_json_atomic(path: str, data: dict) -> None:
    """Ghi JSON qua tệp tạm rồi đổi tên để không để lại tệp dở dang."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
