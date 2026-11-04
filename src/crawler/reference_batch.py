"""Fetch references in bounded S2 batches and resolve incomplete entries."""
from __future__ import annotations

import logging
import math
from urllib.parse import quote
import uuid

from . import reference_scraper as s2
from .observations import combine_request_metrics, request_delta

logger = logging.getLogger(__name__)


class BatchReferences(dict):
    """Per-paper results with cumulative request counters for logging."""
    request_stats: dict


def _result(source_id: str, body: dict) -> s2.ReferenceResult:
    raw, count = body.get("references"), body.get("referenceCount")
    if (not isinstance(raw, list) or not isinstance(count, int) or isinstance(count, bool)
            or count < 0 or (count == 0 and raw)):
        return s2.ReferenceResult([], status="batch_lookup", error_message="Invalid batch reference fields")
    try:
        records = s2._dedupe([s2._record_from_s2(source_id, ref) for ref in raw])
    except s2.ReferenceScrapeError as error:
        return s2.ReferenceResult([], status="batch_lookup", error_message=str(error))
    status = "empty" if count == 0 else "success" if len(raw) >= count else "partial"
    return s2.ReferenceResult(records, status=status, expected_count=count)


def scrape_references_batch(arxiv_ids: list[str], rate_limit_sec: float = 5.0,
                             batch_size: int = 25) -> BatchReferences:
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 500:
        raise ValueError("S2 batch_size must be between 1 and 500")
    if not math.isfinite(rate_limit_sec) or rate_limit_sec < 0:
        raise ValueError("S2 interval must be finite and nonnegative")
    identifiers = list(dict.fromkeys(s2._validate_source_id(value) for value in arxiv_ids))
    results = BatchReferences()

    def fetch(group):
        before = s2.get_request_stats()
        try:
            body = s2._get_json(s2._API_BASE + "/batch", {"fields": s2._PAPER_FIELDS},
                                f"batch {len(group)} bài", rate_limit_sec,
                                method="POST", json_body={"ids": ["ARXIV:" + key for key in group]})
        except s2.BatchRequestSizeError:
            overhead = request_delta(before, s2.get_request_stats())
            if len(group) > 1:
                middle = len(group) // 2
                fetch(group[:middle])
                fetch(group[middle:])
                first = results[group[0]]
                first.request_metrics = combine_request_metrics(overhead, first.request_metrics or {})
                return
            body, failure = [], None
        except s2.ReferenceScrapeError as error:
            body = None
            failure = str(error)
        else:
            failure = None
        delta = request_delta(before, s2.get_request_stats())
        group_id = uuid.uuid4().hex
        indexed, duplicate = {}, set()
        if isinstance(body, list) and len(body) == len(group):
            for item in body:
                if not isinstance(item, dict):
                    continue
                external = item.get("externalIds") or {}
                key = s2._normalize_arxiv_id(external.get("ArXiv")) if isinstance(external, dict) else None
                if key in group:
                    if key in indexed:
                        duplicate.add(key)
                    indexed[key] = item
        for position, key in enumerate(group):
            if failure:
                result = s2.ReferenceResult([], status="api_error", source="none", error_message=failure)
            elif key not in indexed or key in duplicate:
                result = s2.ReferenceResult([], status="batch_lookup", error_message="Batch entry needs an individual lookup")
            else:
                result = _result(key, indexed[key])
            # Attribute each shared HTTP call once, to the first paper in its group.
            result.request_metrics = delta if position == 0 else request_delta({}, {})
            result.request_group, result.request_group_size = group_id, len(group)
            result.request_stats = s2.get_request_stats()
            results[key] = result
        logger.info("S2 batch %d bài: %d đủ, %d cần xử lý tiếp; %d request",
                    len(group), sum(results[key].status in {"success", "empty"} for key in group),
                    sum(results[key].status not in {"success", "empty"} for key in group), delta["requests"])

    for start in range(0, len(identifiers), batch_size):
        fetch(identifiers[start:start + batch_size])
    results.request_stats = s2.get_request_stats()
    return results


def complete_batch_result(source_id: str, result: s2.ReferenceResult,
                          unzipped_paper_dir: str | None, rate_limit_sec: float) -> s2.ReferenceResult:
    """Resolve only entries that the batch could not complete."""
    if result.status == "batch_lookup":
        return s2.scrape_references_for_paper(source_id, unzipped_paper_dir, rate_limit_sec)
    if result.status != "partial":
        return result
    try:
        raw = s2._fetch_s2_pages(f"{s2._API_BASE}/arXiv:{quote(source_id, safe='')}/references", source_id, rate_limit_sec)
        records = s2._dedupe([s2._record_from_s2(source_id, ref) for ref in raw])
    except s2.ReferenceScrapeError as error:
        result.error_message = str(error)
        return result
    if len(raw) >= result.expected_count:
        return s2.ReferenceResult(records, status="success", expected_count=result.expected_count)
    return s2.ReferenceResult(s2._dedupe([*result, *records]), status="partial", expected_count=result.expected_count,
                               error_message="S2 pagination returned fewer references than referenceCount")
