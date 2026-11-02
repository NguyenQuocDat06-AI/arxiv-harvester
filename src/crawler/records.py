"""Merge publication revisions and reference metadata."""
from __future__ import annotations

from copy import deepcopy
import re
import json
from typing import Any, Iterable

from .storage import resolve_paper_source_status

SOURCE_TERMINAL = frozenset({"success", "pdf_only", "no_latex"})
REFERENCE_TERMINAL = frozenset({"success", "empty"})


def base_id(record: dict) -> str:
    return re.sub(r"v\d+$", "", str(record.get("id") or record.get("arxiv_id") or record.get("source_id") or ""))


def version_number(value: Any) -> int:
    match = re.fullmatch(r"v?(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def merge_publications(old: dict | None, new: dict) -> dict:
    result = deepcopy(old or {})
    for key, value in new.items():
        if key != "versions" and value is not None and value != [] and value != "":
            result[key] = deepcopy(value)
    result["id"] = base_id(new) or base_id(result)
    versions: dict[str, dict] = {}
    for record in (old or {}, new):
        for version in record.get("versions") or []:
            tag = str(version.get("version") or "v1")
            merged = versions.setdefault(tag, {"version": tag})
            merged.update({k: deepcopy(v) for k, v in version.items() if v is not None})
    if versions:
        result["versions"] = sorted(versions.values(), key=lambda v: version_number(v["version"]))
        result["source_status"] = resolve_paper_source_status([v.get("source_status") for v in result["versions"]])
        for field in ("size_before_bytes", "size_after_bytes"):
            values = [v[field] for v in result["versions"] if v.get(field) is not None]
            result[field] = sum(values) if values else None
    return result


def reference_key(record: dict) -> tuple:
    source = base_id(record)
    for field in ("ref_arxiv_id", "ref_s2_id", "ref_doi"):
        value = record.get(field)
        if value:
            value = re.sub(r"v\d+$", "", str(value)) if field == "ref_arxiv_id" else str(value).strip().lower()
            return source, field, value
    text = record.get("ref_title") or record.get("raw_citation") or record.get("ref")
    if not text:
        return source, "record", json.dumps(record, sort_keys=True, default=str)
    return source, "text", " ".join(str(text).lower().split())


def merge_references(records: Iterable[dict], *, conflicts: list[dict] | None = None) -> list[dict]:
    result: dict[int, dict] = {}
    aliases: dict[tuple, set[int]] = {}
    group_aliases: dict[int, set[tuple]] = {}
    next_group = 0
    def arxiv_id(row):
        return re.sub(r"v\d+$", "", str(row.get("ref_arxiv_id") or ""))
    for record in records:
        source = base_id(record)
        keys = [(source, field, re.sub(r"v\d+$", "", str(record[field])) if field == "ref_arxiv_id" else str(record[field]).strip().lower())
                for field in ("ref_arxiv_id", "ref_s2_id", "ref_doi") if record.get(field)]
        if not keys:
            keys = [reference_key(record)]
        candidates = set().union(*(aliases.get(k, set()) for k in keys))
        anchor = arxiv_id(record)
        targets = {arxiv_id(result[k]) for k in candidates if arxiv_id(result[k])}
        if anchor:
            matches = sorted(k for k in candidates if not arxiv_id(result[k]) or arxiv_id(result[k]) == anchor)
        elif len(targets) > 1:
            # Leave conflicting arXiv targets unresolved without a direct ID match.
            matches = sorted(k for k in candidates if not arxiv_id(result[k]))
        else:
            matches = sorted(candidates)
        if conflicts is not None and ((anchor and targets - {anchor}) or len(targets) > 1):
            conflicts.append({"arxiv_id": source, "incoming_ref_arxiv_id": anchor or None,
                              "existing_ref_arxiv_ids": sorted(targets),
                              "ref_s2_id": record.get("ref_s2_id"), "ref_doi": record.get("ref_doi")})
        if matches:
            key = matches[0]
        else:
            key = next_group
            next_group += 1
            result[key] = {}
            group_aliases[key] = set()
        current = result[key]
        for other in matches[1:]:
            for field, value in result.pop(other).items():
                if current.get(field) in (None, "", []):
                    current[field] = value
            for alias in group_aliases.pop(other):
                aliases[alias].discard(other)
                aliases[alias].add(key)
                group_aliases[key].add(alias)
        for field, value in record.items():
            if value is not None and value != "" and value != []:
                if field != "source" or current.get(field) != "semantic_scholar":
                    current[field] = deepcopy(value)
        for alias in keys:
            aliases.setdefault(alias, set()).add(key)
            group_aliases[key].add(alias)
    return sorted(result.values(), key=lambda row: tuple(str(x) for x in reference_key(row)))


def sources_complete(record: dict) -> bool:
    versions = record.get("versions") or []
    return bool(versions) and all(v.get("source_status") in SOURCE_TERMINAL for v in versions)


def tex_complete(record: dict) -> bool:
    versions = record.get("versions") or []
    return bool(versions) and all(v.get("source_status") == "success" for v in versions)
