from __future__ import annotations

import re
from dataclasses import dataclass

_RETURN = re.compile(r"\breturn\b")


@dataclass(frozen=True)
class Function:
    name: str
    start: int
    open_brace: int
    close_brace: int

    @property
    def body(self) -> slice:
        return slice(self.open_brace + 1, self.close_brace)


def mask_comments(source: str) -> str:
    out = list(source)
    index, end = 0, len(source)
    while index < end:
        if source.startswith("//", index):
            stop = source.find("\n", index)
            stop = end if stop < 0 else stop
        elif source.startswith("/*", index):
            stop = source.find("*/", index + 2)
            stop = end if stop < 0 else stop + 2
        else:
            index += 1
            continue
        for position in range(index, stop):
            if out[position] != "\n":
                out[position] = " "
        index = stop
    return "".join(out)


def _closing_brace(masked: str, open_brace: int) -> int:
    depth = 0
    for index in range(open_brace, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def find_functions(source: str, name: str) -> list[Function]:
    """Every definition of ``name``, in source order.
    """
    masked = mask_comments(source)

    signature = re.compile(r"\b" + re.escape(name) + r"\s*\([^(){};]*\)\s*\{")
    return [
        Function(
            name=name,
            start=match.start(),
            open_brace=match.end() - 1,
            close_brace=_closing_brace(masked, match.end() - 1),
        )
        for match in signature.finditer(masked)
    ]


def return_statements(source: str, function: Function) -> list[int]:
    masked = mask_comments(source)
    return [m.start() for m in _RETURN.finditer(masked, function.open_brace + 1, function.close_brace)]


def find_calls(source: str, function: Function, name: str) -> list[int]:
    masked = mask_comments(source)
    call = re.compile(r"\b" + re.escape(name) + r"\s*\(")
    return [m.start() for m in call.finditer(masked, function.open_brace + 1, function.close_brace)]


def statement_span(source: str, position: int, body_start: int) -> tuple[int, int]:
    masked = mask_comments(source)

    depth = 0
    for index in range(body_start, position):
        if masked[index] in "([":
            depth += 1
        elif masked[index] in ")]":
            depth -= 1

    start = position
    while start > body_start:
        char = masked[start - 1]
        if char in ")]":
            depth += 1
        elif char in "([":
            depth -= 1
        elif depth == 0 and char in ";{}":
            break
        start -= 1
    while start < position and masked[start].isspace():
        start += 1

    depth = 0
    for index in range(start, len(masked)):
        char = masked[index]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0:
            if char == ";":
                return start, index + 1
            if char in "{}":
                return start, -1
    return start, -1


def line_indent(source: str, position: int) -> str:
    start = source.rfind("\n", 0, position) + 1
    line = source[start:]
    return line[: len(line) - len(line.lstrip())]


def body_indent(source: str, function: Function) -> str:
    body = source[function.body]
    for line in body.splitlines():
        if line.strip():
            return line[: len(line) - len(line.lstrip())]
    return line_indent(source, function.start) + "    "
