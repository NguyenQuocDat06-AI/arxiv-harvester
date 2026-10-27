from src.crawler.rate_limiter import rate_limiter
from src.crawler.exceptions import arXivConnectionError, arXivMalformedXMLError, arXivRateLimitError
import re
import time
import xml.etree.ElementTree as ET
import requests
from dataclasses import dataclass, field

API_URL = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
BATCH_SIZE = 100

@dataclass
class DiscoveryBatchResult(list):
    """extend dict list of batch result"""
    records_by_id: dict[str, dict] = field(default_factory=dict)
    missing_confirmed: set[str] = field(default_factory=set)
    failed_ids: dict[str, str] = field(default_factory=dict)

    def __init__(self, records: list[dict], missing: set[str], failed: dict[str, str]):
        super().__init__(records)
        self.records_by_id = {rec["id"]: rec for rec in records}
        self.missing_confirmed = missing
        self.failed_ids = failed


def _get_text(elem: ET.Element | None) -> str:
    """Extract and normalize text from an element."""
    return " ".join(elem.text.split()) if (elem is not None and elem.text) else ""


def _parse_entry(entry: ET.Element) -> dict | None:
    """Parse one Atom entry element into metadata dictionary."""
    raw_url = _get_text(entry.find("atom:id", NS))
    title = _get_text(entry.find("atom:title", NS))
    authors_raw = [
        _get_text(a.find("atom:name", NS))
        for a in entry.findall("atom:author", NS)
        if _get_text(a.find("atom:name", NS))
    ]
    authors_lower = [a.lower() for a in authors_raw]

    # Skip error arXiv API
    if "api/errors" in raw_url or (title == "Error" and any ("arxiv api core" in a for a in authors_lower)):
        return None

    match = re.search(r"(\d{4}\.\d{4,5})(?:v(\d+))?", raw_url)
    if not match:
        return None

    base_id = match.group(1)
    max_ver = int(match.group(2) or 1)

    published_date = _get_text(entry.find("atom:published", NS)) or None
    update_date = _get_text(entry.find("atom:updated", NS)) or published_date

    versions: list[dict] = []
    for v in range(1, max_ver + 1):
        if v == 1:
            versions.append({
                "version": "v1",
                "created": published_date,
                "provenance": "atom_published" if published_date else "unknown",
            })
        elif v == max_ver:
            versions.append({
                "version": f"v{v}",
                "created": update_date,
                "provenance": "atom_updated" if update_date else "unknown",
            })
        else:
            versions.append({
                "version": f"v{v}",
                "created": None,
                "provenance": "unknown",
            })

    return {
        "id": base_id,
        "title": title,
        "abstract": _get_text(entry.find("atom:summary", NS)),
        "authors": authors_raw,
        "categories": [
            c.attrib["term"]
            for c in entry.findall("atom:category", NS)
            if "term" in c.attrib
        ],
        "primary_category": getattr(
            entry.find("arxiv:primary_category", NS), "attrib", {}
        ).get("term", ""),
        "published": published_date,
        "updated": update_date,
        "doi": _get_text(entry.find("arxiv:doi", NS)) or None,
        "comment": _get_text(entry.find("arxiv:comment", NS)) or None,
        "journal_ref": _get_text(entry.find("arxiv:journal_ref", NS)) or None,
        "versions": versions,
        "version_timestamp_provenance": "atom_direct",
    }


def discover_metadata_batch(
    arxiv_ids: list[str], rate_limit_sec: float = 3.0, max_retries: int = 3
) -> DiscoveryBatchResult:
    """Get metadata for list of arxiv ids with batching, retry and timeout."""
    headers = {
        "User-Agent": "arxiv-harvester/1.0 (Course Project; mailto:24120282@student.hcmus.edu.vn)"
    }
    all_records: list[dict] = []
    missing_confirmed: set[str] = set()
    failed_ids: dict[str, str] = {}

    for i in range(0, len(arxiv_ids), BATCH_SIZE):
        chunk = arxiv_ids[i : i + BATCH_SIZE]
        params = {"id_list": ",".join(chunk), "max_results": len(chunk)}

        resp_text: str | None = None
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            rate_limiter.wait("arxiv", interval=rate_limit_sec)
            try:
                resp = requests.get(
                    API_URL, params=params, headers=headers, timeout=20.0
                )

                if resp.status_code in (429, 503):
                    retry_after = resp.headers.get("Retry-After")
                    sleep_time = (
                        float(retry_after.strip())
                        if (retry_after and retry_after.strip().isdigit())
                        else (attempt + 1) * 5.0
                    )
                    if attempt == max_retries - 1:
                        last_exc = arXivRateLimitError(
                            f"HTTP {resp.status_code} after {attempt + 1} attempts for {chunk[0]}..{chunk[-1]}. Retry after {sleep_time}s",
                            status_code=resp.status_code,
                            retry_after=sleep_time,
                            failed_ids=chunk,
                        )
                        break

                    time.sleep(sleep_time)
                    continue

                resp.raise_for_status()
                resp_text = resp.text
                break

            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 3.0)

        # After retry not got response
        if resp_text is None:
            for cid in chunk:
                failed_ids[cid] = repr(last_exc)
            if isinstance(last_exc, arXivRateLimitError):
                raise last_exc
            raise arXivConnectionError(
                f"No response for chunk {chunk[0]}..{chunk[-1]} after {max_retries} attempts: {last_exc}",
                timeout=20.0,
                endpoint=API_URL,
                failed_ids=chunk,
            ) from last_exc

        try:
            root = ET.fromstring(resp_text)
        except ET.ParseError as exc:
            for cid in chunk:
                failed_ids[cid] = f"Malformed XML: {exc}"
            raise arXivMalformedXMLError(
                f"XML không hợp lệ cho lô {chunk[0]}..{chunk[-1]}: {exc}",
                endpoint=API_URL,
                failed_ids=chunk,
            ) from exc

        chunk_found: set[str] = set()
        for entry in root.findall("atom:entry", NS):
            rec = _parse_entry(entry)
            if rec and rec["id"] in chunk:
                all_records.append(rec)
                chunk_found.add(rec["id"])

        for cid in chunk:
            if cid not in chunk_found:
                missing_confirmed.add(cid)

    return DiscoveryBatchResult(all_records, missing_confirmed, failed_ids)


if __name__ == "__main__":
    import json

    test_ids = [
        "2412.18848",
        "2412.18849",
        "2501.00001",
        "9999.99999", 
    ]

    print(f"[*] Starting metadata discovery test for {len(test_ids)} sample IDs...")
    start_time = time.time()

    data = discover_metadata_batch(test_ids, rate_limit_sec=3.0)

    elapsed = time.time() - start_time
    print(f"[+] Completed in {elapsed:.2f}s. Records retrieved: {len(data)}/{len(test_ids)}")

    if data:
        print("\n--- Sample Record (First Paper) ---")
    sample = data[0]
    print(f"ID: {sample['id']}")
    print(f"Title: {sample['title']}")
    print(f"Authors (list[str]): {sample['authors']}")
    print(f"Primary category: {sample['primary_category']}")
    print(f"Versions count: {len(sample['versions'])}")
    for ver in sample["versions"]:
            print(f"  - {ver['version']}: {ver['created']}")

    print("\n--- Detailed JSON Structure ---")
    print(json.dumps(sample, indent=2, ensure_ascii=False))
