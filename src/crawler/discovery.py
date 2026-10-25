import re
import time
import xml.etree.ElementTree as ET
import requests

API_URL = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
BATCH_SIZE = 100


def _get_text(elem: ET.Element | None) -> str:
    """Extract and normalize text from an element."""
    return " ".join(elem.text.split()) if (elem is not None and elem.text) else ""


def _parse_entry(entry: ET.Element) -> dict | None:
    """Parse one Atom entry element into metadata dictionary."""
    raw_url = _get_text(entry.find("atom:id", NS))

    match = re.search(r"(\d{4}\.\d{4,5})(?:v(\d+))?", raw_url)
    if not match:
        return None

    base_id = match.group(1)
    max_ver = int(match.group(2) or 1)

    published_date = _get_text(entry.find("atom:published", NS))
    update_date = _get_text(entry.find("atom:updated", NS)) or published_date

    versions = [
        {"version": f"v{v}", "created": published_date if v == 1 else update_date}
        for v in range(1, max_ver + 1)
    ]

    return {
        "id": base_id,
        "title": _get_text(entry.find("atom:title", NS)),
        "abstract": _get_text(entry.find("atom:summary", NS)),
        "authors": [
            _get_text(author.find("atom:name", NS))
            for author in entry.findall("atom:author", NS)
            if _get_text(author.find("atom:name", NS))
        ],
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
    }


def discover_metadata_batch(
    arxiv_ids: list[str], rate_limit_sec: float = 3.0, max_retries: int = 3
) -> list[dict]:
    """Get metadata for list of arxiv ids with batching, retry and timeout."""
    results: list[dict] = []
    headers = {
        "User-Agent": "arxiv-harvester/1.0 (Course Project; mailto:24120282@student.hcmus.edu.vn)"
    }

    for i in range(0, len(arxiv_ids), BATCH_SIZE):
        chunk = arxiv_ids[i : i + BATCH_SIZE]
        params = {"id_list": ",".join(chunk), "max_results": len(chunk)}

        time.sleep(rate_limit_sec)

        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    API_URL, params=params, headers=headers, timeout=20.0
                )

                if resp.status_code in (429, 503):
                    backoff = (attempt + 1) * 5.0
                    time.sleep(backoff)
                    continue

                resp.raise_for_status()

                root = ET.fromstring(resp.text)
                for entry in root.findall("atom:entry", NS):
                    rec = _parse_entry(entry)
                    if rec and "error" not in rec["title"].lower():
                        results.append(rec)
                break

            except (requests.RequestException, ET.ParseError) as exc:
                if attempt == max_retries - 1:
                    print(f"Cảnh báo: Lỗi khi tải metadata lô {chunk[0]}..{chunk[-1]}: {exc}")
                time.sleep((attempt + 1) * 3.0)

    return results


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
