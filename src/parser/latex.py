"""Scan TeX groups and commands with limited macro support."""
from __future__ import annotations
from dataclasses import dataclass
import re


@dataclass
class Command:
    name: str
    start: int
    end: int
    args: list[str]
    options: list[str]
    star: bool = False


def group(text: str, start: int, opening="{", closing="}") -> tuple[str, int]:
    if start >= len(text) or text[start] != opening:
        raise ValueError("Expected balanced group")
    depth, index = 1, start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if not depth:
                return text[start + 1:index], index + 1
        index += 1
    raise ValueError("Unclosed TeX group")


def literal_end(text: str, start: int) -> int | None:
    match = re.match(r"\\verb\*?([^A-Za-z\s])", text[start:])
    if match:
        delimiter = match.group(1)
        end = text.find(delimiter, start + match.end())
        return len(text) if end < 0 else end + 1
    match = re.match(r"\\begin\s*\{(verbatim\*?|lstlisting|minted)\}", text[start:])
    if match:
        closing = "\\end{" + match.group(1) + "}"
        end = text.find(closing, start + match.end())
        return len(text) if end < 0 else end + len(closing)
    return None


def strip_comments(text: str) -> str:
    output, index = [], 0
    while index < len(text):
        if text[index] == "\\":
            end = literal_end(text, index)
            if end is not None:
                output.append(text[index:end])
                index = end
                continue
            output.append(text[index:index + 2])
            index += 2
        elif text[index] == "%":
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            output.append(" " * (end - index))
            index = end
        else:
            output.append(text[index])
            index += 1
    return "".join(output)


def command_at(text: str, start: int) -> Command | None:
    match = re.match(r"\\([A-Za-z@]+|[^\s])(?P<star>\*)?", text[start:])
    if not match:
        return None
    name = match.group(1)
    cursor = end = start + match.end()
    args, options = [], []
    declarations = {"small", "footnotesize", "normalsize", "scriptsize", "tiny", "large", "Large", "LARGE",
                    "huge", "Huge", "frenchspacing", "bfseries", "mdseries", "itshape", "upshape", "slshape",
                    "scshape", "rmfamily", "sffamily", "ttfamily", "normalfont", "bf", "it", "rm", "sf", "tt"}
    if name in declarations:
        return Command(name, start, end, [], [], bool(match.group("star")))
    optional_commands = {"begin", "documentclass", "documentstyle", "usepackage", "RequirePackage", "includegraphics",
                         "include", "input", "item", "newcommand", "renewcommand", "providecommand", "newtheorem",
                         "title", "author", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph",
                         "cite", "citep", "citet", "citealt", "citealp", "citeauthor", "citeyear", "citeyearpar",
                         "autocite", "parencite", "textcite", "footcite", "nocite", "bibitem"}
    count = {"newcommand": 2, "renewcommand": 2, "providecommand": 2, "href": 2, "frac": 2,
             "dfrac": 2, "tfrac": 2, "documentclass": 1, "item": 0, "appendix": 0,
             "maketitle": 0, "newblock": 0, "centering": 0, "midrule": 0, "toprule": 0,
             "bottomrule": 0, "printbibliography": 0}.get(name, 1)
    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor < len(text) and text[cursor] == "[" and name in optional_commands:
            value, cursor = group(text, cursor, "[", "]")
            options.append(value)
            end = cursor
        elif cursor < len(text) and text[cursor] == "{" and len(args) < count:
            value, cursor = group(text, cursor)
            args.append(value)
            end = cursor
        else:
            break
    return Command(name, start, end, args, options, bool(match.group("star")))


def commands(text: str):
    index = 0
    while index < len(text):
        if text[index] != "\\":
            index += 1
            continue
        end = literal_end(text, index)
        if end is not None:
            index = end
            continue
        command = command_at(text, index)
        if command:
            yield command
            index = max(index + 1, command.end)
        else:
            index += 1


def environment_end(text: str, start: int, name: str) -> tuple[int, int]:
    depth = 1
    for command in commands(text[start:]):
        if command.args and command.args[0] == name:
            if command.name == "begin":
                depth += 1
            elif command.name == "end":
                depth -= 1
                if depth == 0:
                    return start + command.start, start + command.end
    raise ValueError(f"Unclosed environment {name}")


MATH_ENVIRONMENTS = {"equation", "align", "alignat", "gather", "multline", "eqnarray", "displaymath", "flalign", "subequations", "empheq"}


def simple_math_aliases(text: str) -> dict[str, list[str]]:
    """Find declared display wrappers without arguments."""
    starts, ends = {}, {}
    for command in commands(text):
        if command.name == "begin" and command.args == ["document"]:
            break
        if command.name not in {"newcommand", "renewcommand", "providecommand"} or len(command.args) != 2:
            continue
        if command.options and command.options != ["0"]:
            continue
        name, body = (arg.strip() for arg in command.args)
        if not re.fullmatch(r"\\[A-Za-z@]+", name):
            continue
        match = re.fullmatch(r"\\(begin|end)\s*\{([^{}]+)\}", body)
        if match and match[2].rstrip("*") in MATH_ENVIRONMENTS:
            (starts if match[1] == "begin" else ends)[name[1:]] = match[2]
    return {name: sorted(end for end, target in ends.items() if target == environment)
            for name, environment in starts.items() if environment in ends.values()}


def math_at(text: str, start: int, aliases: dict | None = None) -> tuple[int, str, bool] | None:
    if aliases and text.startswith("\\", start):
        match = re.match(r"\\([A-Za-z@]+)", text[start:])
        if match and match[1] in aliases:
            body_start = start + match.end()
            depth = 1
            for command in commands(text[body_start:]):
                if command.name == match[1]:
                    depth += 1
                elif command.name in aliases[match[1]]:
                    depth -= 1
                    if depth == 0:
                        body_end = body_start + command.start
                        return body_end + 1 + len(command.name), text[body_start:body_end], True
            raise ValueError(f"Unclosed declared math wrapper: {match[1]}")
    for opening, closing, block in (("$$", "$$", True), (r"\[", r"\]", True), (r"\(", r"\)", False), ("$", "$", False)):
        if text.startswith(opening, start):
            cursor = start + len(opening)
            while cursor < len(text):
                if text.startswith(closing, cursor):
                    return cursor + len(closing), text[start + len(opening):cursor], block
                cursor += 2 if text[cursor] == "\\" else 1
            return None
    if text.startswith(r"\begin", start):
        command = command_at(text, start)
        if command and command.args and command.args[0].rstrip("*") in MATH_ENVIRONMENTS:
            body_end, end = environment_end(text, command.end, command.args[0])
            return end, text[command.end:body_end], True
    return None


def sentences(text: str) -> list[str]:
    protected = [False] * len(text)
    index = 0
    while index < len(text):
        math = math_at(text, index)
        command = command_at(text, index) if text[index] == "\\" else None
        end = math[0] if math else command.end if command else index + 1
        if math or command:
            protected[index:end] = [True] * (end - index)
        index = end
    patterns = (r"https?://[^\s{}<>]+", r"\b(?:e\.g\.|i\.e\.|et\s+al\.|Fig\.|Eq\.|Dr\.|Mr\.|Ms\.|Prof\.|etc\.)", r"(?<=\d)\.(?=\d)", r"\b[A-Z]\.(?=\s*[A-Z])")
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I if "https" in pattern or "et" in pattern else 0):
            end = match.end()
            if pattern.startswith("https"):
                end = match.start() + len(match.group().rstrip(".,!?;:"))
            protected[match.start():end] = [True] * (end - match.start())
    output, begin = [], 0
    for index, char in enumerate(text):
        if char in ".!?" and not protected[index] and (index + 1 == len(text) or text[index + 1].isspace()):
            if text[begin:index + 1].strip():
                output.append(text[begin:index + 1].strip())
            begin = index + 1
    if text[begin:].strip():
        output.append(text[begin:].strip())
    return output
