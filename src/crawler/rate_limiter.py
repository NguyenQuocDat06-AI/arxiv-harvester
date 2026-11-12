import time
import threading
import math
from .request_policy import RequestPolicy, CooldownDeferred

class DomainRateLimiter:
    """Track request intervals per domain."""
    def __init__(self, default_interval: float = 3.0) -> None:
        self.default_interval = default_interval
        # Last request time per domain.
        self._last_called: dict[str,float] = {}
        self._not_before: dict[str, float] = {}
        self._lock = threading.Lock()
        self._domain_locks: dict[str, threading.RLock] = {}
        self.policy = RequestPolicy()

    def _domain_lock(self, domain):
        with self._lock:
            return self._domain_locks.setdefault(domain, threading.RLock())

    def defer(self, domain: str, seconds: float) -> None:
        """Apply a server cooldown to subsequent requests."""
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Cooldown must be finite and nonnegative")
        with self._domain_lock(domain):
            self._not_before[domain] = max(self._not_before.get(domain, 0), time.monotonic() + seconds)
            self.policy.defer(domain, seconds)

    def wait(self, domain: str = "arxiv", interval: float | None = None) -> None:
        """ Wait until the next request is allowed."""
        wait_time = interval if interval is not None else self.default_interval
        if not math.isfinite(wait_time) or wait_time < 0:
            raise ValueError("Rate limit interval must be finite and nonnegative")
        while True:
            with self._domain_lock(domain):
                now = time.monotonic()
                remaining = max(wait_time - (now - self._last_called.get(domain, float("-inf"))),
                                self._not_before.get(domain, 0) - now)
                if remaining <= 0:
                    remaining = self.policy.reserve(domain, wait_time)
                if remaining <= 0:
                    self._last_called[domain] = time.monotonic()
                    return
                if remaining > self.policy.max_wait_sec:
                    raise CooldownDeferred(domain, remaining)
            time.sleep(remaining)

    def mark_completed(self, domain: str = "arxiv") -> None:
        """Update last called timestamp when a network transfer finishes."""
        with self._domain_lock(domain):
            self._last_called[domain] = time.monotonic()
            if hasattr(self.policy, "mark_completed"):
                self.policy.mark_completed(domain)

    def mark_heavy_completed(self, domain: str = "arxiv", padding_sec: float = 1.5) -> None:
        """Paces next request conservatively after a heavy transfer or multi-chunk resume."""
        if not math.isfinite(padding_sec) or padding_sec < 0:
            raise ValueError("Padding must be finite and nonnegative")
        with self._domain_lock(domain):
            self._last_called[domain] = time.monotonic() + padding_sec
            if hasattr(self.policy, "mark_completed"):
                self.policy.mark_completed(domain)

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
