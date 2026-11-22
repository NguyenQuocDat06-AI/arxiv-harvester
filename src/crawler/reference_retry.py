"""Retry unfinished references while source downloads continue."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from queue import Empty, Queue
import threading
import time

from .records import merge_references
from .reference_state import retry_remaining

logger = logging.getLogger(__name__)
RETRYABLE = frozenset({'pending', 'api_error', 'bib_pending', 'partial', 'unavailable'})


class ReferenceRetryQueue:
    def __init__(self, executor, resolve, cooldown, batch_size, max_attempts,
                 journal, attempts=None, retry_delay=30.0, poll_interval=0.25):
        self.executor, self.resolve, self.cooldown = executor, resolve, cooldown
        self.batch_size, self.max_attempts = batch_size, max_attempts
        self.journal = Path(journal)
        self.attempts = attempts if attempts is not None else {}
        self.retry_delay, self.poll_interval = retry_delay, poll_interval
        self.pending, self.active = {}, set()
        self.completed = Queue()
        self.lock = threading.Lock()
        self.wake, self.stopping = threading.Event(), threading.Event()
        self.counters = Counter()
        self.thread = threading.Thread(target=self._run, name='S2RetryScheduler', daemon=True)

    def start(self):
        self.thread.start()

    def add(self, item):
        key, _, observation, _ = item
        with self.lock:
            if (self.stopping.is_set() or observation.get('reference_status') not in RETRYABLE
                    or key in self.pending or key in self.active
                    or self.attempts.get(key, 0) >= self.max_attempts):
                return False
            self.pending[key] = (deepcopy(item), time.monotonic()+max(self.retry_delay, retry_remaining(observation)))
            self.counters['enqueued'] += 1
        self.wake.set()
        return True

    def drain(self):
        while True:
            try:
                yield self.completed.get_nowait()
            except Empty:
                return

    def stop(self):
        self.stopping.set()
        self.wake.set()
        self.thread.join()

    def summary(self):
        with self.lock:
            return {**self.counters, 'pending': len(self.pending),
                    'max_attempts_per_paper': self.max_attempts}

    def _event(self, event, **fields):
        row = {'time_utc': datetime.now(timezone.utc).isoformat(), 'event': event, **fields}
        with self.journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')

    def _execute(self, items):
        # A fresh request may have extended cooldown while this batch was queued.
        if self.stopping.is_set() or self.cooldown() > 0:
            return None
        keys = [item[0] for item in items]
        self._event('started', ids=keys)
        logger.info('S2 retry nền: bắt đầu %d bài', len(keys))
        started = time.perf_counter()
        result = self.resolve(items)
        self._event('finished', ids=keys, elapsed_sec=time.perf_counter()-started,
                    statuses=dict(Counter(row[1]['reference_status'] for row in result)))
        return result

    def _collect(self, future, items):
        try:
            rows = future.result()
        except BaseException as error:
            self.completed.put(error)
            rows = None
        with self.lock:
            for item in items:
                self.active.discard(item[0])
            if rows is None:
                for item in items:
                    self.pending[item[0]] = (item, time.monotonic()+self.retry_delay)
                return
            self.counters['batches'] += 1
            original = {item[0]: item for item in items}
            for row in rows:
                key, observation, refs = row[:3]
                self.attempts[key] = self.attempts.get(key, 0)+1
                self.counters['paper_attempts'] += 1
                if observation['reference_status'] in RETRYABLE:
                    if self.attempts[key] < self.max_attempts:
                        old = original[key]
                        combined = refs if observation['reference_update'] == 'replace' else merge_references([*(old[1] or []), *refs])
                        item = (key, combined, observation, old[3])
                        self.pending[key] = (item, time.monotonic()+max(self.retry_delay, retry_remaining(observation)))
                else:
                    self.counters['resolved'] += 1
                self.completed.put(row)

    def _run(self):
        future, items = None, []
        try:
            while not self.stopping.is_set():
                self.wake.clear()
                if future is not None and future.done():
                    self._collect(future, items)
                    future, items = None, []
                delay = self.poll_interval
                if future is None:
                    with self.lock:
                        due = min((due for _, due in self.pending.values()), default=float('inf'))
                    delay = min(5.0, max(self.poll_interval, due-time.monotonic()))
                    if due <= time.monotonic():
                        remaining = self.cooldown()
                        if remaining > 0:
                            delay = min(5.0, remaining)
                        else:
                            with self.lock:
                                keys = [key for key, (_, at) in self.pending.items() if at <= time.monotonic()][:self.batch_size]
                                items = [self.pending.pop(key)[0] for key in keys]
                                self.active.update(keys)
                            if items:
                                future = self.executor.submit(self._execute, items)
                                future.add_done_callback(lambda _: self.wake.set())
                self.wake.wait(delay)
        except BaseException as error:
            self.completed.put(error)
        finally:
            if future is not None:
                if future.cancel():
                    with self.lock:
                        for item in items:
                            self.active.discard(item[0])
                            self.pending[item[0]] = (item, time.monotonic())
                else:
                    self._collect(future, items)
