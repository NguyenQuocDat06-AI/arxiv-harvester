"""Theo dõi tài nguyên. Phụ trách: Trịnh Vỹ Triết (24120474)."""

import json
import os
import platform
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import psutil

# Quy đổi đơn vị: 1 MB trong stats.json = 1024**2 byte (MiB).
BYTES_PER_MB = 1024**2


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
    has_gpu = bool(os.environ.get("CUDA_VISIBLE_DEVICES")) or os.path.exists(
        "/dev/nvidia0"
    )
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
    ) -> None:
        if sample_interval_sec <= 0:
            raise ValueError("sample_interval_sec phải lớn hơn 0")
        self.sample_interval_sec = sample_interval_sec
        self.watch_dirs = dict(watch_dirs or {})
        self._process = psutil.Process()
        self._samples: list[int] = []
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
        self._sample()
        self._start_perf = time.perf_counter()
        self._thread = threading.Thread(
            target=self._sampling_loop, name="resource-profiler", daemon=True
        )
        self._thread.start()

    def _sample(self) -> None:
        try:
            rss = self._process.memory_info().rss
        except psutil.Error:
            return
        with self._lock:
            self._samples.append(rss)

    def _sampling_loop(self) -> None:
        while not self._stop_event.wait(self.sample_interval_sec):
            self._sample()

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Cộng dồn thời gian của một pha, kể cả khi pha đó ném lỗi."""
        begin = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - begin
            self._phase_sec[name] = self._phase_sec.get(name, 0.0) + elapsed
            self._phase_calls[name] = self._phase_calls.get(name, 0) + 1

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
        """Dừng đo, xuất stats.json và trả lại các số đo cùng đơn vị."""
        self._stop()
        if self._result is None:
            with self._lock:
                samples = list(self._samples)
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
                    "metric": "RSS của tiến trình Python (không phải RAM toàn máy)",
                    "unit": "MB",
                    "bytes_per_mb": BYTES_PER_MB,
                    "peak_rss_mb": round(max(samples) / BYTES_PER_MB, 2),
                    "avg_rss_mb": round(statistics.fmean(samples) / BYTES_PER_MB, 2),
                    "os_reported_peak_rss_mb": (
                        round(os_peak / BYTES_PER_MB, 2) if os_peak else None
                    ),
                    "num_samples": len(samples),
                    "sample_interval_sec": self.sample_interval_sec,
                },
                "disk": {
                    "unit": "bytes",
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
        result = {**self._result, **(extra or {})}
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
