"""Resolve the ordered TeX include path without running TeX."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
from .latex import commands, group, strip_comments
from .normalize import normalize

_DOC_CLASS_RE = re.compile(r"\\document(?:class|style)\b")
_TITLE_RE = re.compile(r"\\title\s*(?:\[[^\]]*\]\s*)?\{")
_WORD_RE = re.compile(r"\w+")


@dataclass
class Gathered:
    root: str
    text: str
    files: list[str]
    source_map: list[dict]
    diagnostics: list[str] = field(default_factory=list)
    bibliography_files: list[str] = field(default_factory=list)
    root_selection: str = "unique_candidate"


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError(f"Cannot decode {path}")


def _extract_title(text: str) -> str:
    try:
        title = next((c.args[0] for c in commands(text) if c.name == "title" and c.args), "")
        if title:
            return title
    except ValueError:
        pass
    match = _TITLE_RE.search(text)
    if match:
        try:
            title, _ = group(text, match.end() - 1)
            return title
        except ValueError:
            return ""
    return ""


def _title_tokens(raw: str) -> list[str]:
    if not raw:
        return []
    cleaned = raw.replace("\\\\", " ").replace("~", " ")
    try:
        cleaned = normalize(cleaned)
    except ValueError:
        pass
    return _WORD_RE.findall(cleaned.casefold())


def _is_root_file(path: Path) -> bool:
    text = strip_comments(read_text(path))
    try:
        return any(c.name in {"documentclass", "documentstyle"} for c in commands(text))
    except ValueError:
        return bool(_DOC_CLASS_RE.search(text))


def _select_root(version_dir: str | Path, preferred: str | None = None,
                 expected_title: str | None = None) -> tuple[Path, str]:
    directory = Path(version_dir).resolve()
    if preferred:
        chosen = (directory / preferred).resolve()
        if not chosen.is_relative_to(directory) or not chosen.is_file() or not _is_root_file(chosen):
            raise ValueError("Configured TeX root is invalid")
        return chosen, "configured"
    roots = [p for p in sorted(directory.rglob("*")) if p.is_file() and p.suffix.lower() == ".tex" and _is_root_file(p)]
    if len(roots) == 1:
        return roots[0], "unique_candidate"
    if len(roots) > 1 and expected_title:
        exp_tokens = _title_tokens(expected_title)
        if exp_tokens:
            cand_tokens_map = {p: _title_tokens(_extract_title(strip_comments(read_text(p)))) for p in roots}
            exact = [p for p in roots if cand_tokens_map[p] == exp_tokens]
            if len(exact) == 1:
                return exact[0], "title_match"
            if len(exact) > 1:
                top_level = [p for p in exact if p.parent == directory]
                if len(top_level) == 1:
                    return top_level[0], "title_match_top_level"
            if len(exp_tokens) >= 4:
                exp_set = set(exp_tokens)
                scores = sorted(
                    ((len(exp_set & set(cand_tokens_map[p])) / len(exp_set), p) for p in roots if cand_tokens_map[p]),
                    key=lambda item: item[0],
                    reverse=True,
                )
                if scores and scores[0][0] >= 0.70 and (len(scores) == 1 or scores[1][0] < 0.30):
                    return scores[0][1], "title_similarity_unique"
    raise ValueError(f"Expected one compilation root, found {len(roots)}: {[p.name for p in roots]}")


def find_root(version_dir: str | Path, preferred: str | None = None, expected_title: str | None = None) -> Path:
    return _select_root(version_dir, preferred, expected_title)[0]


def gather(version_dir: str | Path, preferred_root: str | None = None, expected_title: str | None = None) -> Gathered:
    directory = Path(version_dir).resolve()
    root, root_selection = _select_root(directory, preferred_root, expected_title)
    files, source_map, diagnostics = [], [], []
    offset = 0
    finished_document = False
    def expand(path: Path, stack: list[Path]) -> str:
        nonlocal offset, finished_document
        path = path.resolve()
        if not path.is_relative_to(directory):
            diagnostics.append(f"include escapes version directory: {path.name}")
            return ""
        if path in stack:
            diagnostics.append("include cycle: " + " -> ".join(p.name for p in [*stack, path]))
            return ""
        if not path.is_file():
            diagnostics.append(f"missing include: {path.relative_to(directory)}")
            return ""
        relative = path.relative_to(directory).as_posix()
        if relative not in files:
            files.append(relative)
        text = strip_comments(read_text(path))
        pieces, cursor = [], 0
        def append(fragment, source_start):
            nonlocal offset
            if fragment:
                pieces.append(fragment)
                source_map.append({"start": offset, "end": offset + len(fragment), "file": relative,
                                   "source_line": text.count("\n", 0, source_start) + 1})
                offset += len(fragment)
        for command in commands(text):
            if command.name == "endinput":
                append(text[cursor:command.start], cursor)
                cursor = len(text)
                break
            if command.name == "end" and command.args == ["document"]:
                append(text[cursor:command.end], cursor)
                cursor = len(text)
                finished_document = True
                break
            if command.name not in {"input", "include"}:
                continue
            append(text[cursor:command.start], cursor)
            if not command.args or "\\" in command.args[0] or "#" in command.args[0]:
                diagnostics.append(f"dynamic/unsupported include in {relative}")
            else:
                relative_child = Path(command.args[0].strip())
                if not relative_child.suffix:
                    relative_child = relative_child.with_suffix(".tex")
                # TeX resolves ordinary input paths from the compilation directory.
                child = root.parent / relative_child
                if not child.is_file():
                    child = path.parent / relative_child
                append("\n", command.start)
                pieces.append(expand(child, [*stack, path]))
                append("\n", command.end)
                if finished_document:
                    cursor = len(text)
                    break
            cursor = command.end
        append(text[cursor:], cursor)
        return "".join(pieces)
    text = expand(root, [])
    return Gathered(root.relative_to(directory).as_posix(), text, files, source_map, diagnostics, root_selection=root_selection)
