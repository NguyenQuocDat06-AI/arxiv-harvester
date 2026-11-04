"""Persistent provider cooldowns and local process coordination."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import tempfile
import time

logger = logging.getLogger(__name__)


class CooldownDeferred(Exception):
    def __init__(self, provider: str, seconds: float):
        self.provider, self.retry_after = provider, seconds
        super().__init__(f"{provider} đang nghỉ {seconds:.0f}s; giữ checkpoint và chạy lại sau cooldown")


class LocalMutex:
    """OS locks stay on local disk, not on a Drive/FUSE mount."""
    def __init__(self, name: str, timeout: float = 5.0):
        root = Path(tempfile.gettempdir()) / "arxiv-harvester-locks"
        root.mkdir(exist_ok=True)
        self.path = root / (hashlib.sha256(os.path.normcase(name).encode()).hexdigest() + ".lock")
        self.timeout, self.stream = timeout, None

    def __enter__(self):
        self.stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.stream.write(b"0")
            self.stream.flush()
        started = time.monotonic()
        while True:
            try:
                self.stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() - started >= self.timeout:
                    self.stream.close()
                    self.stream = None
                    raise RuntimeError("Một tiến trình khác đang dùng network state này; dừng lượt cũ trước") from None
                time.sleep(0.05)

    def __exit__(self, *args):
        if self.stream is not None:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None


def redact(value, secrets=(), limit=1200):
    text = str(value)
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
        for length in range(len(secret) - 1, 7, -1):
            if text.endswith(secret[:length]):
                text = text[:-length] + "[REDACTED]"
                break
    text = re.sub(r'(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,}\"]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)((?:x-api-key|api[_-]?key|access[_-]?token|token)[\"\s:=]+)[^\s,}\"]+', r'\1[REDACTED]', text)
    return text[:limit]


def retry_after(response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(value)
            server = parsedate_to_datetime(response.headers.get("Date")) if response.headers.get("Date") else datetime.now(timezone.utc)
            target = target.replace(tzinfo=target.tzinfo or timezone.utc)
            server = server.replace(tzinfo=server.tzinfo or timezone.utc)
            return max(0.0, (target - server).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def response_diagnostic(response, secrets=()) -> dict:
    names = {"retry-after", "date", "server", "request-id", "x-request-id", "cf-ray"}
    headers = {key: redact(value, secrets, 256) for key, value in response.headers.items()
               if key.lower() in names or "ratelimit" in key.lower() or key.lower().startswith("rate-limit")}
    content = getattr(response, "_content", b"")
    if not isinstance(content, bytes):
        content = b""
    if not content:
        raw = getattr(response, "raw", None)
        if raw is not None and callable(getattr(raw, "read1", None)):
            try:
                content = raw.read1(2048, decode_content=False)
            except Exception:
                content = b""
    if not isinstance(content, bytes):
        content = b""
    if not content and getattr(response, "raw", None) is None:
        try:
            payload = response.json()
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8") if isinstance(payload, (dict, list, str)) else b""
        except (ValueError, AttributeError, TypeError):
            pass
    return {"status": response.status_code, "headers": headers,
            "response_excerpt": redact(content.decode("utf-8", errors="replace"), secrets)}


class RequestPolicy:
    def __init__(self, state_dir: str | Path | None = None, credential: str = "", max_wait_sec: float = 180):
        if not math.isfinite(max_wait_sec) or max_wait_sec <= 0:
            raise ValueError("max_wait_sec must be positive and finite")
        self.directory = Path(state_dir).resolve() if state_dir is not None else None
        self.credential_tag = hashlib.sha256((credential or "anonymous").encode()).hexdigest()[:20]
        self.credential_present = bool(credential)
        self.max_wait_sec = max_wait_sec
        self.memory = {}
        self.diagnostic_file = None
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)

    def now(self):
        return time.time() if self.directory is not None else time.monotonic()

    @contextmanager
    def state(self, provider):
        key = provider + ("-" + self.credential_tag if provider == "semantic_scholar" else "")
        if self.directory is None:
            yield self.memory.setdefault(key, {})
            return
        path = self.directory / (key + ".json")
        with LocalMutex(str(path)):
            try:
                value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                if not isinstance(value, dict):
                    raise ValueError("Invalid request state")
                for field in ("not_before", "last_request", "interval", "consecutive_429", "successes"):
                    number = value.get(field, 0)
                    if not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
                        raise ValueError("Invalid request state timestamp/counter")
            except (ValueError, OSError) as error:
                raise RuntimeError(f"Không đọc được network state {path.name}; không gửi request") from error
            yield value
            from .profiler import _write_json_atomic
            _write_json_atomic(str(path), value)

    def reserve(self, provider, interval):
        with self.state(provider) as state:
            now = self.now()
            delay = max(0.0, state.get("not_before", 0) - now,
                        state.get("last_request", float("-inf")) + max(interval, state.get("interval", 0)) - now)
            if delay <= 0:
                state["last_request"] = now
            return delay

    def defer(self, provider, seconds):
        with self.state(provider) as state:
            state["not_before"] = max(state.get("not_before", 0), self.now() + seconds)

    def limited(self, provider, response, floor=60.0, secrets=()):
        server_wait = retry_after(response)
        diagnostic = response_diagnostic(response, secrets)
        with self.state(provider) as state:
            streak = min(20, state.get("consecutive_429", 0) + 1)
            base = min(900.0, max(60.0, floor) * 2 ** (streak - 1))
            delay = max(server_wait or 0.0, base + random.uniform(0, base * 0.1))
            state.update(not_before=max(state.get("not_before", 0), self.now() + delay),
                         consecutive_429=streak, successes=0, interval=min(60.0, max(5.0, state.get("interval", 0)) * 2),
                         last_diagnostic=diagnostic, updated_at=time.time())
            next_retry = time.time() + max(0, state["not_before"] - self.now())
        event = {"provider": provider, "received_at": datetime.now(timezone.utc).isoformat(),
                 "cooldown_sec": delay, "next_retry_at": next_retry,
                 "credential_present": bool(secrets) if provider == "semantic_scholar" else False,
                 "credential_tag": hashlib.sha256(secrets[0].encode()).hexdigest()[:20] if provider == "semantic_scholar" and secrets else None,
                 **diagnostic}
        if self.diagnostic_file:
            with LocalMutex(str(self.diagnostic_file)):
                with Path(self.diagnostic_file).open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        logger.warning("HTTP 429: %s", json.dumps(event, ensure_ascii=False))
        return delay

    def succeeded(self, provider):
        with self.state(provider) as state:
            state["consecutive_429"] = 0
            state["successes"] = state.get("successes", 0) + 1
            if state["successes"] >= 2:
                state["interval"] = state.get("interval", 0) * 0.5
                state["successes"] = 0

    def snapshot(self, provider):
        with self.state(provider) as state:
            remaining = max(0.0, state.get("not_before", 0) - self.now())
            return {**state, "remaining_sec": remaining, "next_retry_at": time.time() + remaining}


@contextmanager
def network_runtime(state_dir, credential="", max_wait_sec=180):
    from .rate_limiter import rate_limiter
    directory = Path(state_dir).resolve()
    with LocalMutex("crawler-run:" + str(directory), timeout=0):
        previous = rate_limiter.policy
        previous_times = rate_limiter._last_called, rate_limiter._not_before
        rate_limiter.policy = RequestPolicy(directory, credential, max_wait_sec)
        rate_limiter._last_called, rate_limiter._not_before = {}, {}
        try:
            rate_limiter.policy.snapshot("arxiv")
            rate_limiter.policy.snapshot("semantic_scholar")
            yield rate_limiter.policy
        finally:
            rate_limiter.policy = previous
            rate_limiter._last_called, rate_limiter._not_before = previous_times
