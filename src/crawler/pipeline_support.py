"""Small bounded executors for the crawl pipeline."""
from concurrent.futures import ThreadPoolExecutor
import threading


class BoundedExecutor(ThreadPoolExecutor):
    def __init__(self, max_workers, max_pending, profiler=None, phase_name=None, **kwargs):
        super().__init__(max_workers=max_workers, **kwargs)
        self._slots = threading.BoundedSemaphore(max_pending)
        self._profiler, self._phase_name = profiler, phase_name

    def submit(self, function, /, *args, **kwargs):
        self._slots.acquire()
        def run():
            if self._profiler is not None and self._phase_name is not None:
                with self._profiler.phase(self._phase_name):
                    return function(*args, **kwargs)
            return function(*args, **kwargs)
        try:
            future = super().submit(run)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        return future
