import time

class DomainRateLimiter:
    """ Rate limit for a domain ( arXiv, Semantic, Scholar, ...)"""
    def __init__(self, default_interval: float = 3.0) -> None:
        self.default_interval = default_interval
        # Last time call for domain
        self._last_called: dict[str,float] = {}

    def wait(self, domain: str = "arxiv", interval: float | None = None) -> None:
        """ Wait until the next request is allowed."""
        wait_time = interval if interval is not None else self.default_interval
        now = time.time()
        last_time = self._last_called.get(domain, 0.0)
        elapsed = now - last_time

        if elapsed < wait_time:
            time.sleep(wait_time - elapsed)
        
        self._last_called[domain] = time.time()

rate_limiter = DomainRateLimiter(default_interval=3.0)

if __name__ == "__main__":
    print("=== TEST DOMAIN RATE LIMIT ===")
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

    print("\n[+] Done test.")
