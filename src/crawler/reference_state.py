"""Keep reference evidence separately from the latest request failure."""
import time

TRANSIENT = frozenset({"api_error", "bib_pending", "unavailable"})
BEST_FIELDS = ("reference_status", "reference_source", "expected_count", "received_count",
               "raw_count", "pagination_exhausted", "error_message", "updated_at", "reference_retry_at")


def retry_remaining(observation, now=None):
    return max(0.0, (observation.get("reference_retry_at") or 0.0) - (time.time() if now is None else now))


def needs_individual(observation):
    return bool(observation.get("lookup_required") or observation.get("provider_data_error")
                or observation.get("reference_status") in {"partial", "unavailable"})


def preserve_evidence(previous, current, recheck_sec=21600.0):
    result = dict(current)
    result.update(last_attempt_status=current["reference_status"],
                  last_attempt_error=current.get("error_message"), last_attempt_at=current.get("updated_at"))
    result["last_network_attempt_at"] = (current.get("updated_at") if current.get("requests", 0) > 0
                                          else previous.get("last_network_attempt_at"))
    result["lookup_required"] = bool(previous.get("lookup_required") or current.get("lookup_required"))
    if previous.get("reference_status") == "partial" and (
            current["reference_status"] in TRANSIENT or
            (current["reference_status"] == "partial" and previous.get("pagination_exhausted")
             and not current.get("pagination_exhausted"))):
        for field in BEST_FIELDS:
            result[field] = previous.get(field)
    elif current["reference_status"] == "api_error" and previous.get("reference_status") == "bib_pending":
        for field in BEST_FIELDS:
            result[field] = previous.get(field)
    if (current["reference_status"] == "partial" and current.get("pagination_exhausted")) or current.get("provider_data_error"):
        result["reference_retry_at"] = time.time() + recheck_sec
    return result
