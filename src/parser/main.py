"""Parse source revisions into three tables with resumable checkpoints."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from pathlib import PureWindowsPath
from pathlib import Path
import re
import shutil
import time
import uuid
import pyarrow.parquet as pq
from . import PIPELINE_VERSION
from .gather import gather
from .hierarchy import parse_hierarchy
from .bibliography import extract_entries, unify_entries, cited_keys
from .deduplicate import deduplicate
from .storage import SCHEMAS, write_parquet, validate_rows, validate_directory
from .statistics import summarize

_crawler = "src.crawler" if __package__.startswith("src.") else "crawler"
ResourceProfiler = importlib.import_module(_crawler + ".profiler").ResourceProfiler
write_json = importlib.import_module(_crawler + ".profiler")._write_json_atomic
publication_files = importlib.import_module(_crawler + ".validate_sources").publication_files
merge_publications = importlib.import_module(_crawler + ".records").merge_publications


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def raw_root(raw_dir: Path, paper_id: str, member: str | None = None) -> Path:
    if member and (raw_dir / member / "unzipped").exists():
        return raw_dir / member
    if (raw_dir / "unzipped").exists():
        return raw_dir
    matches = [path.parent for path in raw_dir.glob("*/unzipped") if (path / paper_id.replace("/", "_")).exists()]
    if len(matches) == 1:
        return matches[0]
    return raw_dir


def load_root_overrides(path: str | None) -> dict:
    if path is None:
        return {}
    overrides = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(overrides, dict):
        raise ValueError("Root overrides must be a JSON object keyed by arXiv ID")
    for identifier, value in overrides.items():
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[A-Za-z][\w.-]*/\d{7})", identifier):
            raise ValueError(f"Invalid root override publication: {identifier}")
        if isinstance(value, dict):
            if not value or any(not re.fullmatch(r"v[1-9]\d*", version) for version in value):
                raise ValueError(f"Invalid root override versions for {identifier}")
            paths = value.values()
        else:
            paths = [value]
        for root in paths:
            if (not isinstance(root, str) or not root.strip() or "\\" in root or PureWindowsPath(root).drive
                    or root.startswith("/") or Path(root).is_absolute() or ".." in Path(root).parts or Path(root).suffix.lower() != ".tex"):
                raise ValueError(f"Root override must be a portable relative .tex path: {root!r}")
    return overrides


def fingerprint(paper: dict, raw: Path, code_hash: str, preferred_root: str | dict | None) -> str:
    digest = hashlib.sha256(json.dumps({"paper": paper, "code_hash": code_hash, "preferred_root": preferred_root}, sort_keys=True, default=str).encode())
    for version in paper.get("versions") or []:
        directory = raw / "unzipped" / paper["id"].replace("/", "_") / version["version"]
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".tex", ".bib", ".bbl"}:
                    if not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink():
                        raise ValueError("Source link escapes/is outside the version corpus")
                    digest.update(path.relative_to(directory).as_posix().encode())
                    digest.update(file_hash(path).encode())
    return digest.hexdigest()


def process_publication(paper: dict, raw: Path, preferred_root: str | dict | None = None) -> dict:
    identifier = paper["id"]
    trees, entries, manifests, gathering = {}, [], [], {}
    if not paper.get("versions"):
        manifests.append({"arxiv_id": identifier, "version": None, "has_tex": False,
                          "status": "error_missing_version_metadata", "elements_before": 0, "bibtex_before": 0,
                          "diagnostics": ["Publication has no verified version metadata"], "unresolved_cites": []})
    for version in sorted(paper.get("versions") or [], key=lambda v: int(v["version"][1:])):
        number = int(version["version"][1:])
        directory = raw / "unzipped" / identifier.replace("/", "_") / version["version"]
        started = time.perf_counter()
        has_tex = directory.exists() and any(p.is_file() and p.suffix.lower() == ".tex" for p in directory.rglob("*"))
        manifest = {"arxiv_id": identifier, "version": number, "has_tex": bool(has_tex),
                    "elements_before": 0, "bibtex_before": 0, "counts_measured": False,
                    "diagnostics": [], "unresolved_cites": []}
        if not has_tex:
            manifest["status"] = "empty_no_tex" if version.get("source_status") in {"pdf_only", "no_latex"} else "error_missing_source"
            manifest["counts_measured"] = manifest["status"] == "empty_no_tex"
        else:
            try:
                selected_root = preferred_root.get(version["version"]) if isinstance(preferred_root, dict) else preferred_root
                gathered = gather(directory, selected_root)
                tree = parse_hierarchy(gathered.text)
                bibliography, bib_errors = extract_entries(gathered, directory, number)
                trees[number] = tree
                entries.extend(bibliography)
                gathering[number] = {"root": gathered.root, "files": gathered.files, "source_map": gathered.source_map,
                                     "bibliography_files": gathered.bibliography_files,
                                     "cited_keys": sorted(cited_keys(gathered.text) - {"*"})}
                manifest.update({"root": gathered.root, "root_selection": "configured" if selected_root else "unique_candidate",
                                 "files": gathered.files, "bibliography_files": gathered.bibliography_files,
                                 "elements_before": len(tree.nodes),
                                 "counts_measured": True,
                                 "bibtex_before": len(bibliography), "diagnostics": [*gathered.diagnostics, *tree.diagnostics, *bib_errors]})
                manifest["status"] = "partial" if manifest["diagnostics"] else "success"
            except (ValueError, OSError, UnicodeError) as error:
                manifest.update(status="error", diagnostics=[str(error)])
        manifest["elapsed_sec"] = time.perf_counter() - started
        manifests.append(manifest)
    bibtex, mappings, conflicts = unify_entries(identifier, entries)
    elements, hierarchy, occurrences = deduplicate(identifier, trees, mappings)
    errors = validate_rows(elements, hierarchy, bibtex)
    if errors:
        raise ValueError("; ".join(errors))
    for manifest in manifests:
        version = manifest["version"]
        keys = gathering.get(version, {}).get("cited_keys", [])
        manifest["unresolved_cites"] = [key for key in keys if key not in mappings.get(version, {})]
        if manifest["unresolved_cites"] and manifest["status"] == "success":
            manifest["status"] = "partial"
    if manifests:
        manifests[0]["elements_store_size"] = len(elements)
        manifests[0]["bibtex_store_size"] = len(bibtex)
        manifests[0]["bibliography_conflicts"] = len(conflicts)
    return {"elements": elements, "hierarchy": hierarchy, "bibtex": bibtex, "manifests": manifests,
            "working": {"occurrences": occurrences, "citation_mappings": mappings, "field_conflicts": conflicts,
                        "bibliography_entries": [asdict(entry) for entry in entries], "gathering": gathering}}


def run(publications: str, raw_dir: str, output_dir: str, resume=False, limit: int | None = None,
        preferred_root: str | None = None, sample_interval_sec: float = 0.5,
        root_overrides: str | None = None, min_free_gb: float = 4.0) -> dict:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if not math.isfinite(min_free_gb) or min_free_gb < 0:
        raise ValueError("min_free_gb must be finite and nonnegative")
    overrides = load_root_overrides(root_overrides)
    output, raw = Path(output_dir), Path(raw_dir)
    output.mkdir(parents=True, exist_ok=True)
    papers, members = {}, {}
    for path in publication_files(publications):
        for record in pq.ParquetFile(path).read().to_pylist():
            identifier = str(record.get("id") or record.get("arxiv_id") or "")
            if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[A-Za-z][\w.-]*/\d{7})", identifier):
                raise ValueError(f"Invalid publication ID: {identifier!r}")
            if any(not re.fullmatch(r"v[1-9]\d*", str(v.get("version"))) for v in record.get("versions") or []):
                raise ValueError(f"Invalid version tag for {identifier}")
            papers[identifier] = merge_publications(papers.get(identifier), record)
            members[identifier] = path.parent.name
    if not papers:
        raise ValueError("No publications found")
    papers = dict(sorted(papers.items())[:limit] if limit else sorted(papers.items()))
    checkpoint_path = output / "checkpoint.json"
    if checkpoint_path.exists() and not resume:
        raise ValueError("Output has checkpoint; use --resume or another output directory")
    if not checkpoint_path.exists() and any(output.glob("*/*.parquet")):
        raise ValueError("Output contains tables without checkpoint; use another output directory")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"completed": {}, "scope": []}
    if set(checkpoint.get("scope", [])) - set(papers):
        raise ValueError("New scope excludes existing output papers; use another output directory")
    checkpoint["scope"] = sorted(papers)
    code_hash = hashlib.sha256("".join(file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))).encode()).hexdigest()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True)
    profiler = ResourceProfiler(sample_interval_sec=sample_interval_sec, watch_dirs={"output": str(output)})
    report = {"run_id": run_id, "pipeline_version": PIPELINE_VERSION, "code_hash": code_hash,
              "publications_input": str(publications), "raw_dir": str(raw), "resumed": resume, "processed_this_run": 0, "reused": 0}
    report.update(root_overrides_file=root_overrides, root_overrides_hash=file_hash(Path(root_overrides)) if root_overrides else None,
                  min_free_gb=min_free_gb, unused_root_overrides=sorted(set(overrides) - set(papers)))
    profiler.start()
    manifests = []
    try:
        for identifier, paper in papers.items():
            root = raw_root(raw, identifier, members.get(identifier))
            selected_root = overrides.get(identifier, preferred_root)
            if isinstance(selected_root, dict) and preferred_root:
                selected_root = {v["version"]: selected_root.get(v["version"], preferred_root) for v in paper.get("versions") or []}
            content_hash = fingerprint(paper, root, code_hash, selected_root)
            previous = checkpoint["completed"].get(identifier)
            cached = bool(previous and previous.get("fingerprint") == content_hash and
                          all((output / p).is_file() and file_hash(output / p) == digest for p, digest in previous.get("files", {}).items()))
            key = identifier.replace("/", "_").replace(".", "-")
            if cached:
                record = json.loads((output / "working" / (key + ".json")).read_text(encoding="utf-8"))
                manifests.extend(record["manifests"])
                report["reused"] += 1
                continue
            started = time.perf_counter()
            if shutil.disk_usage(output).free < min_free_gb * 1024**3:
                raise OSError(f"Not enough free disk to parse {identifier}; checkpoint retained, threshold {min_free_gb} GiB")
            with profiler.phase("parse_publication"):
                try:
                    result = process_publication(paper, root, selected_root)
                except (ValueError, OSError, UnicodeError, RecursionError) as error:
                    failed = []
                    for version in paper.get("versions") or [{"version": None}]:
                        number = int(version["version"][1:]) if version["version"] else None
                        directory = root / "unzipped" / identifier.replace("/", "_") / str(version["version"])
                        has_tex = directory.is_dir() and any(path.is_file() and path.suffix.lower() == ".tex" for path in directory.rglob("*"))
                        failed.append({"arxiv_id": identifier, "version": number, "has_tex": has_tex,
                                       "status": "error", "counts_measured": False,
                                       "diagnostics": ["Publication pipeline failed: " + str(error)], "unresolved_cites": []})
                    result = {"elements": [], "hierarchy": [], "bibtex": [], "manifests": failed,
                              "working": {"occurrences": [], "citation_mappings": {}, "field_conflicts": [], "gathering": {}}}
            paths = []
            with profiler.phase("storage"):
                for table, schema in SCHEMAS.items():
                    target = output / table / (key + ".parquet")
                    write_parquet(result[table], schema, target)
                    paths.append(target)
                working = output / "working" / (key + ".json")
                write_json(str(working), {"arxiv_id": identifier, "fingerprint": content_hash,
                                          "manifests": result["manifests"], **result["working"]})
                paths.append(working)
            checkpoint["completed"][identifier] = {"fingerprint": content_hash,
                                                    "files": {p.relative_to(output).as_posix(): file_hash(p) for p in paths},
                                                    "elapsed_sec": time.perf_counter() - started}
            write_json(str(checkpoint_path), checkpoint)
            manifests.extend(result["manifests"])
            report["processed_this_run"] += 1
        with profiler.phase("validation"):
            if shutil.disk_usage(output).free < min_free_gb * 1024**3:
                raise OSError("Not enough free disk for the validation index; checkpoint retained")
            validation = validate_directory(output, set(papers), checkpoint=profiler.capture)
            if not validation["valid"]:
                raise ValueError(str(validation["errors"]))
        report.update(summarize(manifests, list(papers.values())))
        report["validation"] = validation
        report["final_output_bytes"] = sum(p.stat().st_size for name in SCHEMAS for p in (output / name).glob("*.parquet"))
        report["status"] = "completed_with_errors" if any(row["status"] not in {"success", "empty_no_tex"} for row in manifests) else "completed"
        write_json(str(output / "manifest.json"), manifests)
    except BaseException as error:
        report.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", error=repr(error))
        raise
    finally:
        stats = profiler.stop_and_export(str(run_dir / "stats.json"), extra=report)
        stats["avg_sec_per_processed_publication"] = stats["runtime_sec"] / report["processed_this_run"] if report["processed_this_run"] else None
        write_json(str(run_dir / "stats.json"), stats)
        write_json(str(output / "stats.json"), stats)
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publications", required=True)
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--preferred-root")
    parser.add_argument("--root-overrides", help="JSON mapping paper IDs to root paths or per-version root paths")
    parser.add_argument("--min-free-gb", type=float, default=4.0, help="Stop before a new publication if disk is below this threshold")
    parser.add_argument("--sample-interval-sec", type=float, default=0.5)
    result = run(**vars(parser.parse_args(argv)))
    print(json.dumps({key: result.get(key) for key in ("status", "publications", "versions", "status_counts", "runtime_sec", "validation")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
