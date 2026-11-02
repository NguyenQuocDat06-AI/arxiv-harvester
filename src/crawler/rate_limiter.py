import time
import threading
import math

class DomainRateLimiter:
    """Track request intervals per domain."""
    def __init__(self, default_interval: float = 3.0) -> None:
        self.default_interval = default_interval
        # Last request time per domain.
        self._last_called: dict[str,float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str = "arxiv", interval: float | None = None) -> None:
        """ Wait until the next request is allowed."""
        wait_time = interval if interval is not None else self.default_interval
        if not math.isfinite(wait_time) or wait_time < 0:
            raise ValueError("Rate limit interval must be finite and nonnegative")
        with self._lock:
            now = time.monotonic()
            remaining = wait_time - (now - self._last_called.get(domain, float("-inf")))
            if remaining > 0:
                time.sleep(remaining)
            self._last_called[domain] = time.monotonic()

rate_limiter = DomainRateLimiter(default_interval=3.0)

if __name__ == "__main__":
    print("Domain rate limit test")
    limiter = DomainRateLimiter(default_interval=1.0)
    print("\n1. Test same domain 'arxiv':")
    start_total = time.time()
    for i in range(3):
        t0 = time.time()
        limiter.wait("arxiv", interval=1.0)
        t1 = time.time()
        print(f"  - Request {i + 1} to 'arxiv': wait {t1 - t0:.3f}s")

    print("\n2. Test multi domain independent:")
    t_start = time.time()
    limiter.wait("arxiv", interval=1.0)
    print(f"  - Called 'arxiv': {time.time() - t_start:.3f}s")

    t_s2 = time.time()
    limiter.wait("semantic_scholar", interval=0.5)
    print(f"  - Called 'semantic_scholar': {time.time() - t_s2:.3f}s")

    print("\nDone test.")
