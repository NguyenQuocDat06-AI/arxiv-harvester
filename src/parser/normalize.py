"""Remove formatting wrappers and normalize math and citations."""
from __future__ import annotations
import re
import unicodedata
from .latex import command_at, literal_end, math_at

CITES = {"cite", "citep", "citet", "citeauthor", "citeyear", "citealt", "citealp", "citeyearpar",
         "autocite", "parencite", "textcite", "footcite", "nocite"}
WRAPPERS = {"textbf", "textit", "emph", "textrm", "textsf", "texttt", "textsc", "underline", "mbox", "caption", "footnote", "thanks"}
DROP = {"centering", "midrule", "toprule", "bottomrule", "hline", "vspace", "hspace", "label", "small", "footnotesize", "normalsize", "noindent", "bibliographystyle"}


def _citation(command, mapping: dict) -> str:
    keys = list(dict.fromkeys(mapping.get(key.strip(), key.strip()) for key in command.args[-1].split(",")))
    return ("\\" + command.name + ("*" if command.star else "")
            + "".join("[" + option + "]" for option in command.options) + "{" + ",".join(keys) + "}")


def _math_citations(text: str, mapping: dict) -> str:
    if not mapping:
        return text
    pieces, cursor, index = [], 0, 0
    while index < len(text):
        if text[index] != "\\":
            index += 1
            continue
        literal = literal_end(text, index)
        if literal is not None:
            index = literal
            continue
        token = re.match(r"\\([A-Za-z@]+|[^\s])\*?", text[index:])
        command = command_at(text, index) if token and token[1] in CITES else None
        if command and command.args:
            pieces.extend((text[cursor:index], _citation(command, mapping)))
            cursor = index = command.end
        else:
            # Preserve math syntax inside nested arguments.
            index += token.end() if token else 1
    pieces.append(text[cursor:])
    return "".join(pieces)


def normalize_math(body: str) -> str:
    protected = []
    def shield(match):
        protected.append(match.group())
        return f"MATHPROTECTEDTOKEN{len(protected)-1}END"
    body = re.sub(r"\\(?:text|textrm|mbox)\s*\{(?:[^{}]|\{[^{}]*\})*\}", shield, body)
    body = re.sub(r"\s+", " ", body).strip()
    body = re.sub(r"\s*([=+*/^_&])\s*", r"\1", body)
    for index, text in enumerate(protected):
        body = body.replace(f"MATHPROTECTEDTOKEN{index}END", text)
    return body


def normalize(text: str, cite_mapping: dict[str, str] | None = None, kind: str | None = None,
              math_aliases: dict | None = None) -> str:
    mapping = cite_mapping or {}
    if kind == "block_formula":
        return r"\begin{equation}" + normalize_math(_math_citations(text, mapping)) + r"\end{equation}"
    output, index = [], 0
    protected = []
    def protect(value):
        protected.append(value)
        return f"LATEXPROTECTEDTOKEN{len(protected)-1}END"
    while index < len(text):
        literal = literal_end(text, index) if text[index] == "\\" else None
        if literal is not None:
            output.append(protect(text[index:literal]))
            index = literal
            continue
        math = math_at(text, index, math_aliases)
        if math:
            end, body, block = math
            body = normalize_math(_math_citations(body, mapping))
            output.append(protect((r"\begin{equation}" + body + r"\end{equation}") if block else "$" + body + "$"))
            index = end
            continue
        command = command_at(text, index) if text[index] == "\\" else None
        if command:
            if command.name in CITES and command.args:
                output.append(_citation(command, mapping))
            elif command.name in WRAPPERS and command.args:
                output.append(normalize(command.args[-1], mapping, math_aliases=math_aliases))
            elif command.name == "href" and len(command.args) == 2:
                output.append(normalize(command.args[1], mapping, math_aliases=math_aliases) + " (" + command.args[0] + ")")
            elif command.name in {"begin", "end", "item"} and kind in {"environment", "list", "item"}:
                output.append(text[index:command.end])
            elif command.name in DROP or command.name in {"begin", "end", "item", "newblock"}:
                output.append(" ")
            elif command.name in {"%", "$", "&", "#", "_", "{", "}"}:
                output.append(command.name)
            elif command.name in {"\\", ",", ";", "!", " "}:
                output.append(" ")
            else:
                output.append(text[index:command.end])
            index = command.end
        else:
            # Remove grouping braces from prose.
            output.append(text[index] if text[index] not in "{}" else "")
            index += 1
    result = re.sub(r"\s+", " ", unicodedata.normalize("NFC", "".join(output))).strip()
    for index, value in enumerate(protected):
        result = result.replace(f"LATEXPROTECTEDTOKEN{index}END", value)
    return result
