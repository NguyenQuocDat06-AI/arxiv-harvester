"""Flat Parquet tables and structural validation for Milestone 2."""
from __future__ import annotations
from collections import defaultdict, deque
from pathlib import Path
import os
import sqlite3
import tempfile
import pyarrow as pa
import pyarrow.parquet as pq

CATEGORY = pa.dictionary(pa.int32(), pa.string())
ELEMENTS_SCHEMA = pa.schema([pa.field("element_id", pa.string(), nullable=False), pa.field("arxiv_id", pa.string(), nullable=False),
                             pa.field("kind", CATEGORY), pa.field("content", pa.string())])
HIERARCHY_SCHEMA = pa.schema([pa.field("arxiv_id", pa.string(), nullable=False), pa.field("version", pa.int32()),
                              pa.field("element_id", pa.string(), nullable=False), pa.field("parent_id", pa.string(), nullable=False)])
BIBTEX_SCHEMA = pa.schema([pa.field("arxiv_id", pa.string(), nullable=False), pa.field("citation_key", pa.string(), nullable=False),
                          pa.field("entry_type", CATEGORY), pa.field("title", pa.string()), pa.field("authors", pa.list_(pa.string())),
                          pa.field("year", pa.int32()), pa.field("doi", pa.string()), pa.field("journal", pa.string()), pa.field("url", pa.string())])
SCHEMAS = {"elements": ELEMENTS_SCHEMA, "hierarchy": HIERARCHY_SCHEMA, "bibtex": BIBTEX_SCHEMA}


def _graph_errors(graph: dict, kinds: dict) -> list[str]:
    nodes = set(graph) | {child for children in graph.values() for child in children}
    incoming = dict.fromkeys(nodes, 0)
    for children in graph.values():
        for child in children:
            incoming[child] += 1
    roots = [node for node, degree in incoming.items() if degree == 0]
    errors = []
    if len(roots) != 1 or kinds.get(roots[0]) != "document":
        errors.append("hierarchy must have one document root")
    pending = deque(roots)
    visited = 0
    while pending:
        node = pending.popleft()
        visited += 1
        for child in graph.get(node, ()):
            incoming[child] -= 1
            if incoming[child] == 0:
                pending.append(child)
    if visited != len(nodes):
        errors.append("hierarchy cycle")
    return errors


def write_parquet(rows: list[dict], schema: pa.Schema, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), temporary, compression="snappy")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_rows(elements: list[dict], hierarchy: list[dict], bibtex: list[dict]) -> list[str]:
    errors = []
    store = {row["element_id"]: row for row in elements}
    if len(store) != len(elements):
        errors.append("duplicate element ID")
    if any(not isinstance(row.get("element_id"), str) or not row.get("element_id")
           or not isinstance(row.get("arxiv_id"), str) or not row.get("arxiv_id") for row in elements):
        errors.append("missing element/publication key")
    keys = [(row["arxiv_id"], row["citation_key"]) for row in bibtex]
    if len(keys) != len(set(keys)):
        errors.append("duplicate citation key")
    if any(not paper or not key for paper, key in keys):
        errors.append("missing citation/publication key")
    graphs = defaultdict(lambda: defaultdict(set))
    edge_keys = set()
    for edge in hierarchy:
        paper, version, child, parent = edge["arxiv_id"], edge["version"], edge["element_id"], edge["parent_id"]
        key = (paper, version, child, parent)
        if key in edge_keys:
            errors.append("duplicate hierarchy edge")
        edge_keys.add(key)
        if version is None or isinstance(version, bool) or not isinstance(version, int) or version < 1:
            errors.append("invalid hierarchy version")
        if child not in store or parent not in store:
            errors.append("missing node or parent")
            continue
        if store[child]["arxiv_id"] != paper or store[parent]["arxiv_id"] != paper:
            errors.append("cross-publication edge")
        graphs[(paper, version)][parent].add(child)
    for graph in graphs.values():
        errors.extend(_graph_errors(graph, {key: row.get("kind") for key, row in store.items()}))
    child_ids = {row.get("element_id") for row in hierarchy}
    if any(row.get("kind") != "document" and row.get("element_id") not in child_ids for row in elements):
        errors.append("element has no hierarchy occurrence")
    for row in elements:
        prefix = str(row.get("arxiv_id") or "").replace("/", "_").replace(".", "-") + "#"
        if not isinstance(row.get("element_id"), str) or not row["element_id"].startswith(prefix):
            errors.append("element ID does not start with publication key")
    return sorted(set(errors))


def validate_directory(output_dir: str | Path, papers: set[str] | None = None, checkpoint=None) -> dict:
    """Validate across shards using a disk index and one version graph at a time."""
    root = Path(output_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    handle = tempfile.NamedTemporaryFile(prefix=".validation-", suffix=".sqlite", dir=root, delete=False)
    index = Path(handle.name)
    handle.close()
    connection = sqlite3.connect(index)
    counts = dict.fromkeys(SCHEMAS, 0)
    errors = set()
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA cache_size=-8192")
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("CREATE TABLE elements (id TEXT PRIMARY KEY, paper TEXT NOT NULL, kind TEXT)")
        connection.execute("CREATE INDEX element_paper ON elements(paper)")
        connection.execute("CREATE TABLE hierarchy (paper TEXT, version INTEGER, child TEXT, parent TEXT, PRIMARY KEY(paper,version,child,parent))")
        connection.execute("CREATE INDEX hierarchy_child ON hierarchy(child)")
        connection.execute("CREATE TABLE bibtex (paper TEXT, citation TEXT, PRIMARY KEY(paper,citation))")
        statements = {"elements": "INSERT OR IGNORE INTO elements VALUES (?,?,?)",
                      "hierarchy": "INSERT OR IGNORE INTO hierarchy VALUES (?,?,?,?)",
                      "bibtex": "INSERT OR IGNORE INTO bibtex VALUES (?,?)"}
        duplicate_messages = {"elements": "duplicate element ID", "hierarchy": "duplicate hierarchy edge", "bibtex": "duplicate citation key"}
        for name, schema in SCHEMAS.items():
            paths = sorted((root / name).glob("*.parquet"))
            if not paths:
                errors.add("missing table shards: " + name)
            for path in paths:
                source = pq.ParquetFile(path)
                counts[name] += source.metadata.num_rows
                if not source.schema_arrow.equals(schema, check_metadata=False):
                    errors.add(f"schema mismatch: {path}")
                    continue
                columns = {"elements": ["element_id", "arxiv_id", "kind"],
                           "hierarchy": ["arxiv_id", "version", "element_id", "parent_id"],
                           "bibtex": ["arxiv_id", "citation_key"]}[name]
                for batch in source.iter_batches(batch_size=2048, columns=columns):
                    values = []
                    for row in batch.to_pylist():
                        paper = row.get("arxiv_id")
                        if not paper:
                            errors.add("missing publication key")
                            continue
                        if papers is not None and paper not in papers:
                            errors.add(f"{name}: publication outside M1 input")
                        if name == "elements":
                            identifier = row.get("element_id")
                            prefix = paper.replace("/", "_").replace(".", "-") + "#"
                            if not identifier or not identifier.startswith(prefix):
                                errors.add("element ID does not start with publication key")
                            if not identifier:
                                continue
                            values.append((identifier, paper, row.get("kind")))
                        elif name == "hierarchy":
                            version = row.get("version")
                            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                                errors.add("invalid hierarchy version")
                                continue
                            if not row.get("element_id") or not row.get("parent_id"):
                                errors.add("missing node or parent")
                                continue
                            values.append((paper, version, row["element_id"], row["parent_id"]))
                        else:
                            if not row.get("citation_key"):
                                errors.add("missing citation/publication key")
                                continue
                            values.append((paper, row["citation_key"]))
                    cursor = connection.executemany(statements[name], values)
                    if cursor.rowcount != len(values):
                        errors.add(duplicate_messages[name])
            connection.commit()
        if checkpoint:
            checkpoint()
        missing = connection.execute("SELECT 1 FROM hierarchy h LEFT JOIN elements c ON c.id=h.child LEFT JOIN elements p ON p.id=h.parent WHERE c.id IS NULL OR p.id IS NULL LIMIT 1").fetchone()
        if missing:
            errors.add("missing node or parent")
        crossed = connection.execute("SELECT 1 FROM hierarchy h JOIN elements c ON c.id=h.child JOIN elements p ON p.id=h.parent WHERE c.paper!=h.paper OR p.paper!=h.paper LIMIT 1").fetchone()
        if crossed:
            errors.add("cross-publication edge")
        unused = connection.execute("SELECT 1 FROM elements e WHERE e.kind IS NOT 'document' AND NOT EXISTS (SELECT 1 FROM hierarchy h WHERE h.child=e.id) LIMIT 1").fetchone()
        if unused:
            errors.add("element has no hierarchy occurrence")
        current_paper, kinds = None, {}
        for paper, version in connection.execute("SELECT DISTINCT paper,version FROM hierarchy ORDER BY paper,version"):
            if paper != current_paper:
                kinds = dict(connection.execute("SELECT id,kind FROM elements WHERE paper=?", (paper,)))
                current_paper = paper
            graph = defaultdict(set)
            for child, parent in connection.execute("SELECT child,parent FROM hierarchy WHERE paper=? AND version=?", (paper, version)):
                graph[parent].add(child)
            errors.update(_graph_errors(graph, kinds))
        return {"valid": not errors, "errors": sorted(errors), "rows": counts,
                "method": "parquet batches, disk-backed key index, one version graph at a time"}
    finally:
        connection.close()
        index.unlink(missing_ok=True)
