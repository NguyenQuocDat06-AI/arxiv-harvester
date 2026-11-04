"""Persist crawl observations separately from course export tables."""
from __future__ import annotations
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from .storage import _write_parquet_atomic

CRAWL_STATUS_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("reference_status", pa.string()), pa.field("reference_source", pa.string()),
    pa.field("expected_count", pa.int64()), pa.field("received_count", pa.int64()),
    pa.field("requests", pa.int64()), pa.field("retries", pa.int64()),
    pa.field("backoff_sec", pa.float64()), pa.field("rate_limit_wait_sec", pa.float64()),
    pa.field("http_status_counts", pa.string()), pa.field("error_message", pa.string()),
    pa.field("updated_at", pa.string()), pa.field("reference_update", pa.string()),
    pa.field("request_group", pa.string()), pa.field("request_group_size", pa.int64()),
])


def save_observations(records: list[dict], path: str | Path) -> None:
    _write_parquet_atomic(pa.Table.from_pylist(records, schema=CRAWL_STATUS_SCHEMA), str(path))


def read_observations(path: str | Path) -> dict[str, dict]:
    path = Path(path)
    if not path.exists():
        return {}
    return {row["arxiv_id"]: row for row in pq.ParquetFile(path).read().to_pylist()}


def request_delta(before: dict, after: dict) -> dict:
    result = {name: max(0, after.get(name, 0) - before.get(name, 0))
              for name in ("requests", "retries", "backoff_sec", "rate_limit_wait_sec")}
    result["http_status_counts"] = json.dumps({key: max(0, value - before.get("by_status", {}).get(key, 0))
                                               for key, value in after.get("by_status", {}).items()}, sort_keys=True)
    return result


def combine_request_metrics(*values: dict) -> dict:
    result = request_delta({}, {})
    statuses = {}
    for value in values:
        for key in ("requests", "retries", "backoff_sec", "rate_limit_wait_sec"):
            result[key] += value.get(key, 0)
        for key, count in json.loads(value.get("http_status_counts") or "{}").items():
            statuses[key] = statuses.get(key, 0) + count
    result["http_status_counts"] = json.dumps(statuses, sort_keys=True)
    return result
