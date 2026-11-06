"""Refresh reference metadata and retain API provenance."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
import pyarrow.parquet as pq
from . import reference_scraper as s2
from .records import base_id, merge_references, REFERENCE_TERMINAL
from .observations import read_observations, save_observations, request_delta
from .storage import save_publications_parquet, save_references_parquet
from .profiler import _write_json_atomic


def enrich_references(shard_dir: str, output_dir: str, raw_dir: str | None = None, execute=False,
                      limit: int | None = None, enrich_targets=False) -> dict:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    source, output = Path(shard_dir), Path(output_dir)
    if source.resolve() == output.resolve():
        raise ValueError("Use a separate output directory")
    papers = pq.ParquetFile(source / "publications.parquet").read().to_pylist()
    references = pq.ParquetFile(source / "references.parquet").read().to_pylist()
    observations = read_observations(source / "crawl_status.parquet")
    if (output / "references.parquet").exists():
        references = merge_references([*references, *pq.ParquetFile(output / "references.parquet").read().to_pylist()])
    observations.update(read_observations(output / "crawl_status.parquet"))
    grouped = {base_id(p): [] for p in papers}
    for reference in references:
        grouped.setdefault(base_id(reference), []).append(reference)
    selected = [p for p in papers if observations.get(base_id(p), {}).get("reference_status") not in REFERENCE_TERMINAL]
    selected = selected[:limit] if limit else selected
    report = {"planned_papers": len(selected), "execute": execute, "queried_papers": 0, "target_metadata_added": 0,
              "field_provenance": [], "errors": {}}
    output.mkdir(parents=True, exist_ok=True)
    if execute:
        for paper in selected:
            identifier = base_id(paper)
            before = s2.get_request_stats()
            local = str(Path(raw_dir) / "unzipped" / identifier.replace("/", "_")) if raw_dir else None
            result = s2.scrape_references_for_paper(identifier, local)
            old = [] if result.status in REFERENCE_TERMINAL else grouped.get(identifier, [])
            grouped[identifier] = merge_references([*old, *result])
            observations[identifier] = {"arxiv_id": identifier, "reference_status": result.status,
                                        "reference_source": result.source, "expected_count": result.expected_count,
                                        "received_count": len(result), "updated_at": datetime.now(timezone.utc).isoformat(),
                                        "error_message": result.error_message, "reference_update": "replace" if result.status in REFERENCE_TERMINAL else "merge",
                                        **request_delta(before, s2.get_request_stats())}
            report["queried_papers"] += 1
            # Save progress after each publication.
            save_references_parquet([r for rows in grouped.values() for r in rows], str(output / "references.parquet"))
            save_observations(list(observations.values()), output / "crawl_status.parquet")
            cooldown = s2.rate_limiter.policy.snapshot("semantic_scholar")["remaining_sec"]
            if cooldown > 0 and result.status == "api_error":
                report.update(status="paused_rate_limit", retry_after_sec=cooldown)
                break
        if enrich_targets and report.get("status") != "paused_rate_limit":
            cache_dir = output / "metadata_cache"
            cache_dir.mkdir(exist_ok=True)
            targets_done = set()
            for rows in grouped.values():
                if report.get("status") == "paused_rate_limit":
                    break
                for reference in rows:
                    identifier = reference.get("ref_arxiv_id")
                    fields = ("ref_s2_id", "ref_title", "ref_authors", "ref_year", "ref_doi", "ref_venue", "ref_submission_date")
                    if not identifier or all(reference.get(field) for field in fields):
                        continue
                    cache = cache_dir / (identifier.replace("/", "_") + ".json")
                    try:
                        if cache.exists():
                            metadata = json.loads(cache.read_text(encoding="utf-8"))
                        else:
                            if identifier in targets_done:
                                continue
                            if limit is not None and len(targets_done) >= limit:
                                continue
                            targets_done.add(identifier)
                            metadata = s2._get_json(f"{s2._API_BASE}/arXiv:{identifier}",
                                                    {"fields": "paperId,title,authors,year,publicationDate,venue,externalIds"}, identifier, 3.1)
                            _write_json_atomic(str(cache), metadata)
                        enriched = s2._record_from_s2(reference["arxiv_id"], metadata)
                        changed = []
                        for field in fields:
                            if not reference.get(field) and enriched.get(field):
                                reference[field] = enriched[field]
                                changed.append(field)
                        if changed:
                            report["target_metadata_added"] += 1
                            report["field_provenance"].append({"arxiv_id": reference["arxiv_id"], "ref_arxiv_id": identifier,
                                                                "fields": changed, "metadata_source": "semantic_scholar",
                                                                "edge_source": reference.get("source"),
                                                                "date_source": "semantic_scholar.publicationDate" if "ref_submission_date" in changed else None,
                                                                "publication_date": metadata.get("publicationDate")})
                        # QA permits publicationDate here; existing dates and edge provenance stay unchanged.
                    except Exception as error:
                        report["errors"][identifier] = str(error)
                        cooldown = s2.rate_limiter.policy.snapshot("semantic_scholar")["remaining_sec"]
                        if cooldown > 0:
                            report.update(status="paused_rate_limit", retry_after_sec=cooldown)
                            break
        save_publications_parquet(papers, str(output / "publications.parquet"))
        save_references_parquet(merge_references(r for rows in grouped.values() for r in rows), str(output / "references.parquet"))
        save_observations(list(observations.values()), output / "crawl_status.parquet")
    _write_json_atomic(str(output / "enrichment_report.json"), report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--raw-dir")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--enrich-targets", action="store_true")
    parser.add_argument("--rate-state-dir")
    args = vars(parser.parse_args(argv))
    state_dir = args.pop("rate_state_dir") or str(Path(args["output_dir"]) / "_request_state")
    from .request_policy import network_runtime
    with network_runtime(state_dir, s2._api_headers().get("x-api-key", "")):
        s2.configure_request_policy()
        print(json.dumps(enrich_references(**args), ensure_ascii=True))


if __name__ == "__main__":
    main()
