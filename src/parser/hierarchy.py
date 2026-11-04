"""Build version trees with sentence, math and figure leaves."""
from __future__ import annotations
from dataclasses import dataclass, field
import re
from .latex import command_at, commands, environment_end, literal_end, math_at, sentences, simple_math_aliases


@dataclass
class Node:
    node_id: int
    parent_id: int | None
    kind: str
    content: str
    start: int
    end: int
    order: int


@dataclass
class Hierarchy:
    nodes: list[Node]
    diagnostics: list[str] = field(default_factory=list)
    math_aliases: dict = field(default_factory=dict)


LEVELS = {"chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4, "paragraph": 5, "subparagraph": 6}
LISTS = {"itemize", "enumerate", "description"}
LAYOUT_ENVIRONMENTS = {"sloppypar", "center", "flushleft", "flushright", "spacing", "onehalfspace", "doublespace", "singlespace", "small", "footnotesize"}


def _paragraph_spans(text: str, aliases: dict):
    """Split only at blank lines outside TeX groups, commands and math."""
    start = index = depth = 0
    while index < len(text):
        if text[index] == "\\":
            end = literal_end(text, index)
            if end is not None:
                index = end
                continue
        math = math_at(text, index, aliases)
        if math:
            index = math[0]
            continue
        if text[index] == "\\":
            command = command_at(text, index)
            if command:
                index = command.end
                continue
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth = max(0, depth - 1)
        elif text[index] == "\n" and depth == 0:
            separator = re.match(r"\n\s*\n", text[index:])
            if separator:
                yield start, index
                index += separator.end()
                start = index
                continue
        index += 1
    yield start, len(text)


def parse_hierarchy(text: str) -> Hierarchy:
    aliases = simple_math_aliases(text)
    title = next((c.args[0] for c in commands(text) if c.name == "title" and c.args), "Document")
    nodes = [Node(0, None, "document", title, 0, len(text), 0)]
    diagnostics = []
    headings = [(0, 0)]
    containers = []
    layout = []
    pending, pending_start = [], 0
    index = 0
    document = next((c for c in commands(text) if c.name == "begin" and c.args == ["document"]), None)
    if document:
        index = document.end
    else:
        diagnostics.append("missing document environment")
    skip_level = None

    def active():
        if containers and containers[-1][1] > headings[-1][1]:
            return containers[-1][1]
        return headings[-1][1]

    def add(kind, content, start, end, parent=None):
        node_id = len(nodes)
        nodes.append(Node(node_id, active() if parent is None else parent, kind, content, start, end, node_id))
        return node_id

    def flush(end):
        nonlocal pending
        prose = "".join(pending)
        pending = []
        if skip_level is not None or not prose.strip():
            return
        for start, finish in _paragraph_spans(prose, aliases):
            paragraph = prose[start:finish]
            if not paragraph.strip():
                continue
            position = pending_start + start
            paragraph_end = pending_start + finish
            parent = add("paragraph", paragraph.strip(), position, paragraph_end)
            for sentence in sentences(paragraph):
                add("sentence", sentence, position, paragraph_end, parent=parent)

    while index < len(text):
        if text[index] == "\\":
            literal = literal_end(text, index)
            if literal is not None:
                if not pending:
                    pending_start = index
                pending.append(text[index:literal])
                index = literal
                continue
        math = math_at(text, index, aliases)
        if math:
            end, body, block = math
            if block:
                flush(index)
                if skip_level is None:
                    add("block_formula", body.strip(), index, end)
            else:
                if not pending:
                    pending_start = index
                pending.append(text[index:end])
            index = end
            continue
        command = command_at(text, index) if text[index] == "\\" else None
        if command and command.name in LEVELS:
            flush(index)
            level = LEVELS[command.name]
            heading = command.args[0] if command.args else ""
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if re.fullmatch(r"\s*(references|bibliography|literature cited)\s*", heading, flags=re.I):
                skip_level = level
            if skip_level is None:
                while len(headings) > 1 and headings[-1][0] >= level:
                    headings.pop()
                parent = headings[-1][1]
                node = add(command.name, heading, index, command.end, parent=parent)
                headings.append((level, node))
            index = command.end
            continue
        if command and command.name == "begin" and command.args:
            name = command.args[0]
            if name in LAYOUT_ENVIRONMENTS:
                flush(index)
                layout.append(name)
                index = command.end
                continue
            if name == "thebibliography" or name.rstrip("*") in {"figure", "table"}:
                flush(index)
                body_end, end = environment_end(text, command.end, name)
                if name != "thebibliography" and skip_level is None:
                    add("figure", text[command.end:body_end].strip(), index, end)
                index = end
                continue
            if name != "document" and skip_level is None:
                flush(index)
                node = add("list" if name in LISTS else "environment", "", index, command.end)
                containers.append((name, node, index, list(headings)))
                index = command.end
                continue
        if command and command.name == "item":
            flush(index)
            if containers and containers[-1][0] == "item":
                _, node, start, old_headings = containers.pop()
                nodes[node].content, nodes[node].end = text[start:index], index
                headings[:] = old_headings
            if not containers or containers[-1][0] not in LISTS:
                diagnostics.append("item outside supported list")
            else:
                node = add("item", "", index, command.end)
                containers.append(("item", node, command.end, list(headings)))
            index = command.end
            continue
        if command and command.name == "end" and command.args:
            flush(index)
            name = command.args[0]
            if name in LAYOUT_ENVIRONMENTS:
                if not layout or layout.pop() != name:
                    diagnostics.append(f"unmatched layout environment: {name}")
                index = command.end
                continue
            if name == "document":
                break
            if containers and containers[-1][0] == "item" and name in LISTS:
                _, node, start, old_headings = containers.pop()
                nodes[node].content, nodes[node].end = text[start:index], index
                headings[:] = old_headings
            if containers and containers[-1][0] == name:
                _, node, start, old_headings = containers.pop()
                nodes[node].content, nodes[node].end = text[start:command.end], command.end
                headings[:] = old_headings
            elif skip_level is None:
                diagnostics.append(f"unmatched end environment: {name}")
            index = command.end
            continue
        if command and command.name in {"bibliography", "bibliographystyle", "addbibresource", "printbibliography", "appendix", "maketitle"}:
            flush(index)
            index = command.end
            continue
        if not pending:
            pending_start = index
        if command:
            pending.append(text[index:command.end])
            index = command.end
        else:
            pending.append(text[index])
            index += 1
    flush(index)
    if containers:
        diagnostics.append("unclosed environments: " + ", ".join(c[0] for c in containers))
    if layout:
        diagnostics.append("unclosed layout environments: " + ", ".join(layout))
    return Hierarchy(nodes, diagnostics, aliases)
