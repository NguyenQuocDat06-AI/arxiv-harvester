"""Resolve the ordered TeX include path without running TeX."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .latex import commands, strip_comments


@dataclass
class Gathered:
    root: str
    text: str
    files: list[str]
    source_map: list[dict]
    diagnostics: list[str] = field(default_factory=list)
    bibliography_files: list[str] = field(default_factory=list)


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError(f"Cannot decode {path}")


def find_root(version_dir: str | Path, preferred: str | None = None) -> Path:
    directory = Path(version_dir).resolve()
    def is_root(path):
        return any(c.name in {"documentclass", "documentstyle"} for c in commands(strip_comments(read_text(path))))
    if preferred:
        chosen = (directory / preferred).resolve()
        if not chosen.is_relative_to(directory) or not chosen.is_file() or not is_root(chosen):
            raise ValueError("Configured TeX root is invalid")
        return chosen
    roots = [p for p in sorted(directory.rglob("*")) if p.is_file() and p.suffix.lower() == ".tex" and is_root(p)]
    if len(roots) != 1:
        raise ValueError(f"Expected one compilation root, found {len(roots)}: {[p.name for p in roots]}")
    return roots[0]


def gather(version_dir: str | Path, preferred_root: str | None = None) -> Gathered:
    directory = Path(version_dir).resolve()
    root = find_root(directory, preferred_root)
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
    return Gathered(root.relative_to(directory).as_posix(), text, files, source_map, diagnostics)
