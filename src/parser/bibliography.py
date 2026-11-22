"""Extract BibTeX, merge fields and map citation keys per version."""
from __future__ import annotations
from dataclasses import dataclass, field
from bisect import bisect_right
import hashlib
from pathlib import Path
import re
from .gather import Gathered, read_text
from .latex import commands, group, sentences, strip_comments
from .normalize import CITES, normalize


_BARE_VAL_RE = re.compile(r"[^,#\s]+")
_FIELD_RE = re.compile(r"[\s,]*([A-Za-z][\w-]*)\s*=\s*")
_AT_START_RE = re.compile(r"@[A-Za-z]+\s*([({])")
_ENTRY_RE = re.compile(r"@([A-Za-z]+)\s*([{(])")
_BIB_TOKEN_RE = re.compile(r'[\\@{}"()%]')
_NEWBLOCK_RE = re.compile(r"\\newblock\s*")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s{}]+")
_AND_RE = re.compile(r"\s+and\s+", flags=re.I)
_DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", flags=re.I)
_ARXIV_EPRINT_RE = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?|[A-Za-z][\w.-]*/\d{7}(?:v\d+)?")
_WORD_RE = re.compile(r"\w+")


@dataclass
class Entry:
    key: str
    entry_type: str
    fields: dict
    version: int
    raw: str


def _value(text: str, index: int, macros: dict) -> tuple[str, int]:
    values = []
    length = len(text)
    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            break
        if text[index] == "{":
            value, index = group(text, index)
        elif text[index] == '"':
            begin, index = index + 1, index + 1
            depth = 0
            while index < length:
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == '"' and not depth:
                    break
                depth += text[index] == "{"
                depth -= text[index] == "}"
                index += 1
            if index >= length:
                raise ValueError("Unclosed BibTeX quote")
            value = text[begin:index]
            index += 1
        else:
            match = _BARE_VAL_RE.match(text, index)
            if not match:
                break
            value = match.group()
            index = match.end()
            value = macros.get(value.lower(), value)
        values.append(value)
        while index < length and text[index].isspace():
            index += 1
        if index < length and text[index] == "#":
            index += 1
        else:
            break
    return "".join(values), index


def _fields(body: str, macros: dict) -> dict:
    result, index, length = {}, 0, len(body)
    while index < length:
        match = _FIELD_RE.match(body, index)
        if not match:
            if body[index:].strip(", \n\t\r"):
                raise ValueError("Unsupported/malformed BibTeX field")
            break
        index = match.end()
        value, index = _value(body, index, macros)
        result[match.group(1).lower()] = value
    return result


def _strip_bib_comments(text: str) -> str:
    """Remove comments outside field values, preserving percent-encoded URLs."""
    if "%" not in text:
        return text
    pieces, last_copy, index, length = [], 0, 0, len(text)
    depth, entry, quoted = 0, None, False
    while index < length:
        match = _BIB_TOKEN_RE.search(text, index)
        if not match:
            break
        pos = match.start()
        char = text[pos]
        if char == "\\":
            index = pos + 2
            continue
        if entry is None and char == "@":
            at_match = _AT_START_RE.match(text, pos)
            if at_match:
                entry = at_match.group(1)
                depth = 1 if entry == "{" else 0
                index = at_match.end()
                continue
        if entry is not None:
            if char == '"' and (entry == "(" and depth == 0 or entry == "{" and depth == 1):
                quoted = not quoted
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if not quoted and entry == "{" and depth == 0:
                    entry = None
            elif char == ")" and not quoted and entry == "(" and depth == 0:
                entry = None
        outside_value = entry is None or (not quoted and depth == (1 if entry == "{" else 0))
        if char == "%" and outside_value:
            end = text.find("\n", pos)
            end = length if end < 0 else end
            if pos > last_copy:
                pieces.append(text[last_copy:pos])
            pieces.append(" " * (end - pos))
            last_copy = index = end
            continue
        index = pos + 1
    if last_copy == 0:
        return text
    if last_copy < length:
        pieces.append(text[last_copy:])
    return "".join(pieces)


def parse_bibtex(text: str, version: int, macros: dict | None = None,
                 wanted_keys: set[str] | None = None) -> list[Entry]:
    text = _strip_bib_comments(text)
    macros = macros if macros is not None else {}
    needed = set(wanted_keys) if wanted_keys is not None else None
    output, deferred, cursor = [], {}, 0
    while match := _ENTRY_RE.search(text, cursor):
        start = match.start()
        opening = match.end() - 1
        if text[opening] == "{":
            content, end = group(text, opening)
        else:
            position, depth, quoted = opening + 1, 0, False
            length = len(text)
            while position < length:
                char = text[position]
                if char == "\\":
                    position += 2
                    continue
                if char == '"' and not depth:
                    quoted = not quoted
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                elif char == ")" and not depth and not quoted:
                    break
                position += 1
            if position >= length:
                raise ValueError("Unclosed BibTeX entry")
            content, end = text[opening + 1:position], position + 1
        kind = match.group(1).lower()
        cursor = end
        if kind in {"preamble", "comment"}:
            continue
        if kind == "string":
            macros.update(_fields(content, macros))
            continue
        key, separator, body = content.partition(",")
        clean_key = key.strip()
        if not separator or not clean_key:
            if needed is None:
                raise ValueError("BibTeX entry lacks key/fields")
            continue
        if needed is not None and clean_key not in needed:
            body_start = opening + 1 + len(key) + len(separator)
            deferred.setdefault(clean_key, []).append((kind, start, end, body_start, end - 1))
            continue
        parsed_fields = _fields(body, macros)
        if needed is not None and parsed_fields.get("crossref"):
            needed.add(parsed_fields["crossref"])
        output.append(Entry(clean_key, kind, parsed_fields, version, text[start:end]))
    if needed is not None and deferred:
        resolved = {entry.key for entry in output}
        queue = [k for k in needed if k not in resolved and k in deferred]
        while queue:
            target = queue.pop()
            if target in resolved:
                continue
            resolved.add(target)
            for kind, s, e, bs, be in deferred.get(target, ()):
                parsed_fields = _fields(text[bs:be], macros)
                output.append(Entry(target, kind, parsed_fields, version, text[s:e]))
                parent = parsed_fields.get("crossref")
                if parent and parent not in resolved and parent in deferred:
                    queue.append(parent)
    return output


def _authors(value: str | None) -> list[str]:
    if not value:
        return []
    output, begin, depth, index = [], 0, 0, 0
    length = len(value)
    while index < length:
        if value[index] == "\\":
            index += 2
            continue
        depth += value[index] == "{"
        depth -= value[index] == "}"
        match = _AND_RE.match(value, index) if not depth else None
        if match:
            output.append(normalize(value[begin:index]))
            index = match.end()
            begin = index
        else:
            index += 1
    output.append(normalize(value[begin:]))
    return [name for name in output if name]


def cited_keys(text: str) -> set[str]:
    keys = set()
    for command in commands(text):
        if command.name in CITES and command.args:
            keys.update(
                cleaned
                for raw_key in command.args[-1].split(",")
                if (cleaned := raw_key.strip().strip("{}").strip())
            )
        elif command.name in {"textbf", "textit", "emph", "footnote", "caption"}:
            for arg in command.args:
                keys.update(cited_keys(arg))
    return keys


def parse_bibitems(text: str, version: int) -> list[Entry]:
    """Recover available fields while keeping the original citation text."""
    text = strip_comments(text)
    entries = []
    bibitems = [command for command in commands(text) if command.name == "bibitem" and command.args]
    for index, command in enumerate(bibitems):
        end = bibitems[index + 1].start if index + 1 < len(bibitems) else text.find(r"\end{thebibliography}", command.end)
        end = len(text) if end < 0 else end
        raw = text[command.end:end].strip()
        pieces = [part.strip() for part in _NEWBLOCK_RE.split(raw) if part.strip()]
        if len(pieces) < 2:
            pieces = sentences(raw)
        fields = {}
        year = _YEAR_RE.search(raw)
        if year:
            fields["year"] = year.group()
        doi = _DOI_RE.search(raw)
        if doi:
            fields["doi"] = doi.group().rstrip(".,;")
        if len(pieces) >= 2:
            fields["author"] = normalize(pieces[0]).rstrip(".")
            fields["title"] = normalize(pieces[1]).rstrip(".")
        entries.append(Entry(command.args[0], "misc", fields, version, raw))
    return entries


def _compiled_bibliography(gathered: Gathered, directory: Path, candidates: list[Path], version: int):
    root_bbl = (directory / gathered.root).with_suffix(".bbl")
    options = [root_bbl] if root_bbl.exists() else list(dict.fromkeys(p for p in candidates if p.exists()))
    if len(options) > 1:
        return [], ["ambiguous compiled bibliography; original .bbl files retained"]
    if not options:
        return [], []
    path = options[0].resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        return [], ["unsafe compiled bibliography path"]
    relative = path.relative_to(directory).as_posix()
    try:
        entries = parse_bibitems(read_text(path), version)
    except (OSError, ValueError) as error:
        return [], [f"unreadable compiled bibliography {relative}: {error}"]
    if relative not in gathered.bibliography_files:
        gathered.bibliography_files.append(relative)
    if not entries:
        return [], [f"unsupported/empty compiled bibliography: {relative}; original retained"]
    return entries, []


def extract_entries(gathered: Gathered, version_dir: str | Path, version: int) -> tuple[list[Entry], list[str]]:
    directory = Path(version_dir).resolve()
    files, diagnostics, entries = set(), [], []
    missing, bbl_candidates, has_bibliography = [], [], False
    macros = {}
    used = cited_keys(gathered.text)
    wanted_filter = None if "*" in used else set(used)
    source_starts = [row["start"] for row in gathered.source_map]
    for command in commands(gathered.text):
        location = bisect_right(source_starts, command.start) - 1
        filename = gathered.source_map[location]["file"] if location >= 0 else gathered.root
        if command.name == "printbibliography":
            has_bibliography = True
        if command.name not in {"bibliography", "addbibresource"} or not command.args:
            continue
        has_bibliography = True
        for name in command.args[0].split(","):
            path = (directory / filename).parent / name.strip()
            if not path.suffix:
                path = path.with_suffix(".bib")
            bbl_candidates.append(path.with_suffix(".bbl"))
            path = path.resolve()
            if not path.is_relative_to(directory):
                diagnostics.append(f"unsafe bibliography: {name}")
            elif not path.is_file():
                missing.append(f"missing/unsafe bibliography: {name}")
            elif path not in files:
                files.add(path)
                try:
                    parsed = parse_bibtex(read_text(path), version, macros, wanted_keys=wanted_filter)
                    entries.extend(parsed)
                    if wanted_filter is not None:
                        wanted_filter.update(
                            e.fields["crossref"] for e in parsed if e.fields.get("crossref")
                        )
                    relative = path.relative_to(directory).as_posix()
                    if relative not in gathered.bibliography_files:
                        gathered.bibliography_files.append(relative)
                except ValueError as error:
                    missing.append(f"{path.name}: {error}")
    dedup_bib, bib_seen = [], {}
    for entry in entries:
        if entry.key in bib_seen:
            if bib_seen[entry.key].raw != entry.raw:
                diagnostics.append(f"duplicate citation key in bibliography: {entry.key}")
            continue
        bib_seen[entry.key] = entry
        dedup_bib.append(entry)
    entries = dedup_bib

    inline_raw = parse_bibitems(gathered.text, version)
    inline, inline_seen = [], {}
    for entry in inline_raw:
        if entry.key in bib_seen:
            continue
        if entry.key in inline_seen:
            if inline_seen[entry.key].raw != entry.raw:
                diagnostics.append(f"duplicate citation key in inline bibliography: {entry.key}")
            continue
        inline_seen[entry.key] = entry
        inline.append(entry)
    known = set(bib_seen) | set(inline_seen)
    root_bbl = (directory / gathered.root).with_suffix(".bbl")
    missing_cites = (used - {"*"}) - known
    recovered = []
    if (has_bibliography and (missing or not known or missing_cites)) or (missing_cites and root_bbl.is_file()):
        recovered, errors = _compiled_bibliography(gathered, directory, bbl_candidates, version)
        diagnostics.extend(errors)
        if recovered:
            missing = []
    diagnostics.extend(missing)
    if "*" not in used:
        # Include crossref parents of cited entries.
        by_key = {entry.key: entry for entry in entries}
        wanted = set(used)
        for _ in range(len(entries)):
            extra = {by_key[key].fields["crossref"] for key in wanted if key in by_key and by_key[key].fields.get("crossref")}
            if extra.issubset(wanted):
                break
            wanted.update(extra)
        entries = [entry for entry in entries if entry.key in wanted]
    entries.extend(inline)
    recovered_seen = set()
    for entry in recovered:
        if entry.key not in known and entry.key not in recovered_seen:
            recovered_seen.add(entry.key)
            entries.append(entry)
    return entries, diagnostics


def _fingerprint(text) -> str:
    return " ".join(_WORD_RE.findall(normalize(str(text or "")).casefold()))


def _author_signature(text) -> str:
    return "|".join(sorted(" ".join(sorted(_WORD_RE.findall(author.casefold()))) for author in _authors(text)))


def unify_entries(paper_id: str, entries: list[Entry]) -> tuple[list[dict], dict[int, dict[str, str]], list[dict]]:
    groups, aliases, mappings, conflicts = [], {}, {}, []
    for entry in sorted(entries, key=lambda e: (e.version, e.key, e.raw)):
        fields = dict(entry.fields)
        doi = _DOI_PREFIX_RE.sub("", fields.get("doi", "")).strip().lower()
        strong = [("doi", doi)] if doi else []
        eprint = fields.get("eprint", "").strip()
        if _ARXIV_EPRINT_RE.fullmatch(eprint):
            strong.append(("arxiv", re.sub(r"v\d+$", "", eprint)))
        index = next((aliases[key] for key in strong if key in aliases), None)
        if index is None and fields.get("title") and fields.get("author"):
            signature = (_fingerprint(fields["title"]), _author_signature(fields["author"]))
            candidates = [i for i, old in enumerate(groups) if old["signature"] == signature
                          and not (old["fields"].get("year") and fields.get("year") and old["fields"]["year"] != fields["year"])
                          and not (old["fields"].get("doi") and doi and old["fields"]["doi"].lower() != doi)]
            if len(candidates) == 1:
                index = candidates[0]
        if index is None:
            identical = next((i for i, old in enumerate(groups) if old["raw"] == entry.raw), None)
            index = identical
        if index is None:
            key = entry.key
            used = {old["key"] for old in groups}
            if key in used:
                key += "_" + hashlib.sha256(entry.raw.encode()).hexdigest()[:10]
            index = len(groups)
            groups.append({"key": key, "entry_type": entry.entry_type, "fields": {}, "raw": entry.raw,
                           "signature": (_fingerprint(fields.get("title")), _author_signature(fields.get("author")))})
        old = groups[index]
        if doi:
            fields["doi"] = doi
        for name, value in fields.items():
            if not value:
                continue
            if old["fields"].get(name) and old["fields"][name] != value:
                conflicts.append({"citation_key": old["key"], "field": name, "retained": old["fields"][name], "alternative": value, "version": entry.version})
            else:
                old["fields"][name] = value
        for alias in strong:
            aliases[alias] = index
        version_map = mappings.setdefault(entry.version, {})
        if entry.key in version_map and version_map[entry.key] != old["key"]:
            raise ValueError(f"Ambiguous duplicate citation key {entry.key} inside version {entry.version}")
        version_map[entry.key] = old["key"]
    rows = []
    for entry in groups:
        fields = entry["fields"]
        year = fields.get("year", "")
        rows.append({"arxiv_id": paper_id, "citation_key": entry["key"], "entry_type": entry["entry_type"],
                     "title": normalize(fields["title"]) if fields.get("title") else None,
                     "authors": _authors(fields.get("author")), "year": int(year) if re.fullmatch(r"\d{4}", year) else None,
                     "doi": fields.get("doi"), "journal": normalize(fields["journal"]) if fields.get("journal") else None,
                     "url": fields.get("url")})
    return rows, mappings, conflicts
