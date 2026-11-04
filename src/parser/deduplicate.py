"""Deduplicate content across versions and retain occurrence mappings."""
from __future__ import annotations
from dataclasses import asdict
import hashlib
from .hierarchy import Hierarchy
from .normalize import normalize


def deduplicate(paper_id: str, trees: dict[int, Hierarchy], mappings: dict[int, dict]) -> tuple[list[dict], list[dict], list[dict]]:
    lookup, elements, edges, occurrences = {}, [], set(), []
    prefix = paper_id.replace("/", "_").replace(".", "-")
    for version, tree in sorted(trees.items()):
        local = {}
        for node in tree.nodes:
            content = normalize(node.content, mappings.get(version), kind=node.kind, math_aliases=tree.math_aliases)
            key = (node.kind, content)
            if key not in lookup:
                digest = hashlib.sha256((node.kind + "\0" + content).encode("utf-8")).hexdigest()
                element_id = prefix + "#" + digest
                lookup[key] = element_id
                elements.append({"arxiv_id": paper_id, "element_id": element_id, "kind": node.kind, "content": content})
            element_id = lookup[key]
            local[node.node_id] = element_id
            occurrences.append({"version": version, **asdict(node), "element_id": element_id, "normalized_content": content})
        for node in tree.nodes:
            if node.parent_id is not None:
                child, parent = local[node.node_id], local[node.parent_id]
                if child == parent:
                    raise ValueError("Deduplication would create a self-edge; inspect structural content")
                edges.add((version, child, parent))
    rows = [{"arxiv_id": paper_id, "version": version, "element_id": child, "parent_id": parent}
            for version, child, parent in sorted(edges)]
    return sorted(elements, key=lambda row: row["element_id"]), rows, occurrences
