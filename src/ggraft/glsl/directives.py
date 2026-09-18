from __future__ import annotations

INCLUDE = "#include"
MOJ_IMPORT = "#moj_import"
DIRECTIVES = (INCLUDE, MOJ_IMPORT)

_current = INCLUDE


def use(directive: str) -> None:
    if directive not in DIRECTIVES:
        raise ValueError(f"unknown import directive {directive!r}")
    global _current
    _current = directive


def current() -> str:
    return _current


def include_line(reference: str) -> str:
    return f"{_current} <{reference}>"
