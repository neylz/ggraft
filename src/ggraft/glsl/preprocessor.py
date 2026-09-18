from __future__ import annotations

import re
from typing import Iterator, Pattern

_OPEN = re.compile(r"^\s*#\s*(?:if|ifdef|ifndef)\b")
_CLOSE = re.compile(r"^\s*#\s*endif\b")
_VERSION = re.compile(r"^\s*#\s*version\b")
_EXTENSION = re.compile(r"^\s*#\s*extension\b")
_INCLUDE = re.compile(r"^\s*#\s*(?:include|moj_import)\b")


def walk(lines: list[str]) -> Iterator[tuple[int, str, int]]:
    """Yields ``(index, line, depth)``, depth being conditional nesting level.

    An ``#if`` and its ``#endif`` report the depth of the enclosing block,
    so the directives themselves read as top-level while their contents do not.
    """
    depth = 0
    for index, line in enumerate(lines):
        if _CLOSE.match(line):
            depth = max(depth - 1, 0)
            yield index, line, depth
        elif _OPEN.match(line):
            yield index, line, depth
            depth += 1
        else:
            yield index, line, depth


def top_level(lines: list[str], pattern: Pattern[str]) -> list[int]:
    return [i for i, line, depth in walk(lines) if depth == 0 and pattern.match(line)]


def declaration_line(source: str) -> int:
    """Index of the line a new top-level declaration should follow, or -1."""
    lines = source.splitlines()
    for pattern in (_INCLUDE, _EXTENSION, _VERSION):
        hits = top_level(lines, pattern)
        if hits:
            return hits[-1]
    return -1


def header_line(source: str) -> int:
    # #version as first statement
    hits = top_level(source.splitlines(), _VERSION)
    return hits[-1] if hits else -1


def insert_after(source: str, index: int, text: str) -> str:
    """Insert ``text`` after ``index`` (-1 for the top), preserving line endings."""
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.split(newline)
    addition = text.split("\n")
    at = index + 1
    return newline.join(lines[:at] + addition + lines[at:])


def declares(source: str, text: str) -> bool:
    # depth 0 only: a match inside #ifdef leaves other variants undeclared
    wanted = text.strip()
    return any(
        line.strip() == wanted
        for _, line, depth in walk(source.splitlines())
        if depth == 0
    )
