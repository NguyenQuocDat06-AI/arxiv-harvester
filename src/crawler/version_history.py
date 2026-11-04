"""Read revision dates from arXivRaw OAI-PMH or a local snapshot.

arXivRaw: https://info.arxiv.org/help/oa/index.html
"""
from __future__ import annotations
import argparse
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import requests
import pyarrow.parquet as pq
from .records import base_id, version_number
from .rate_limiter import rate_limiter
from .storage import save_publications_parquet
from .profiler import _write_json_atomic

OAI_URL = "https://oaipmh.arxiv.org/oai"


def parse_date(value) -> datetime | None:
    if isinstance(value, datetime):
        date = value
    elif value:
        try:
            date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            try:
                date = parsedate_to_datetime(str(value))
            except (ValueError, TypeError):
                return None
    else:
        return None
    return date.astimezone(timezone.utc) if date.tzinfo else None


def parse_oai_history(xml: str, expected_id: str) -> dict:
    root = ET.fromstring(xml)
    local = lambda node: node.tag.rsplit("}", 1)[-1]
    errors = [node for node in root.iter() if local(node) == "error"]
    if errors:
        raise ValueError("OAI: " + "; ".join("".join(e.itertext()) for e in errors))
    raw = next((node for node in root.iter() if local(node) == "arXivRaw"), None)
    if raw is None:
        raise ValueError("OAI response has no arXivRaw record")
    identifier = next((node.text for node in raw if local(node) == "id"), None)
    if identifier != expected_id:
        raise ValueError("OAI record ID does not match requested paper")
    versions = []
    for node in raw:
        if local(node) != "version":
            continue
        tag = node.get("version", "")
        if not re.fullmatch(r"v[1-9]\d*", tag):
            raise ValueError("Invalid OAI revision tag")
        text = next((child.text for child in node if local(child) == "date"), None)
        date = parse_date(text)
        if date is None:
            raise ValueError(f"Invalid OAI revision date for {tag}")
        versions.append({"version": tag, "created": date.isoformat()})
    if not versions or len({v["version"] for v in versions}) != len(versions):
        raise ValueError("Empty/duplicate revision history")
    versions.sort(key=lambda v: version_number(v["version"]))
    if [v["version"] for v in versions] != [f"v{i}" for i in range(1, len(versions) + 1)]:
        raise ValueError("Noncontiguous revision history")
    if [v["created"] for v in versions] != sorted(v["created"] for v in versions):
        raise ValueError("Revision dates are not chronological")
    return {"id": expected_id, "versions": versions, "source": OAI_URL + " (arXivRaw)",
            "fetched_at": datetime.now(timezone.utc).isoformat()}


def fetch_history(paper_id: str, cache_dir: str | Path, session=None, refresh=False) -> dict:
    if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[A-Za-z][A-Za-z0-9.-]*/\d{7})", paper_id):
        raise ValueError("Invalid arXiv ID")
    cache = Path(cache_dir) / (paper_id.replace("/", "_") + ".json")
    if cache.exists() and not refresh:
        history = json.loads(cache.read_text(encoding="utf-8"))
        if history.get("id") != paper_id:
            raise ValueError("Cached history ID mismatch")
        return history
    client = session or requests.Session()
    try:
        for attempt in range(4):
            rate_limiter.wait("arxiv", interval=3.0)
            response = client.get(OAI_URL, params={"verb": "GetRecord", "identifier": "oai:arXiv.org:" + paper_id,
                                                 "metadataPrefix": "arXivRaw"}, timeout=45,
                                  headers={"User-Agent": "arxiv-harvester/0.2 (course revision-history reconciliation)"})
            if response.status_code == 429:
                from .exceptions import arXivRateLimitError
                delay = rate_limiter.policy.limited("arxiv", response)
                raise arXivRateLimitError("arXiv OAI HTTP 429; giữ cache", retry_after=delay, failed_ids=[paper_id])
            if response.status_code == 503 and attempt < 3:
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    date = parse_date(retry)
                    delay = max(0, (date - datetime.now(timezone.utc)).total_seconds()) if date else 3 * (2 ** attempt)
                time.sleep(max(3.0, delay))
                continue
            response.raise_for_status()
            rate_limiter.policy.succeeded("arxiv")
            history = parse_oai_history(response.text, paper_id)
            _write_json_atomic(str(cache), history)
            return history
        raise RuntimeError("OAI retries exhausted")
    finally:
        if session is None:
            client.close()


def reconcile_dates(publications: str, output: str, cache_dir: str, snapshot: str | None = None,
                    fetch_missing: bool = False, limit: int | None = None) -> dict:
    records = pq.ParquetFile(publications).read().to_pylist()
    indexed = {}
    if snapshot:
        wanted = {base_id(p) for p in records}
        with open(snapshot, encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if base_id(row) in wanted:
                    indexed[base_id(row)] = row
    evidence, errors, fetched = [], {}, 0
    before = sum(v.get("created") is None for p in records for v in p.get("versions", []))
    for paper in records:
        if not any(v.get("created") is None for v in paper.get("versions", [])):
            continue
        identifier = base_id(paper)
        history = indexed.get(identifier)
        source = "local_snapshot" if history else "arXivRaw"
        if history is None:
            cached = Path(cache_dir) / (identifier.replace("/", "_") + ".json")
            if cached.exists() or (fetch_missing and (limit is None or fetched < limit)):
                try:
                    fetched += not cached.exists()
                    history = fetch_history(identifier, cache_dir)
                except Exception as error:
                    errors[identifier] = str(error)
                    if rate_limiter.policy.snapshot("arxiv")["remaining_sec"] > 0:
                        break
        if history is None:
            continue
        dates = {v["version"]: parse_date(v.get("created")) for v in history.get("versions", [])}
        for version in paper.get("versions", []):
            date = dates.get(version["version"])
            if version.get("created") is None and date is not None:
                version["created"] = date
                evidence.append({"arxiv_id": identifier, "version": version["version"], "created": date.isoformat(),
                                 "source": source, "source_file": snapshot if source == "local_snapshot" else str(Path(cache_dir))})
    save_publications_parquet(records, output)
    report = {"missing_before": before, "dates_added": len(evidence), "errors": errors,
              "missing_after": sum(v.get("created") is None for p in records for v in p.get("versions", [])), "evidence": evidence}
    if errors and rate_limiter.policy.snapshot("arxiv")["remaining_sec"] > 0:
        report.update(status="paused_rate_limit", retry_after_sec=rate_limiter.policy.snapshot("arxiv")["remaining_sec"])
    _write_json_atomic(str(Path(output).with_suffix(".history.json")), report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publications", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-dir", default="data/cache/version_history")
    parser.add_argument("--snapshot", help="Local arXiv JSONL snapshot with versions/created")
    parser.add_argument("--fetch-missing", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rate-state-dir")
    args = vars(parser.parse_args(argv))
    state_dir = args.pop("rate_state_dir") or str(Path(args["output"]).parent / "_request_state")
    from .request_policy import network_runtime
    with network_runtime(state_dir):
        print(json.dumps(reconcile_dates(**args), ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
