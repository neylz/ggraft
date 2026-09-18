from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, ClassVar

from ggraft import glsl
from ggraft.errors import PatchError
from ggraft.patching.anchor import Anchor, substitute

_REGISTRY: dict[str, type["Operation"]] = {}


def register(name: str) -> Callable[[type["Operation"]], type["Operation"]]:
    def decorate(cls: type["Operation"]) -> type["Operation"]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return decorate


def get(name: str, where: str) -> type["Operation"]:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise PatchError(f"{where}: unknown operation {name!r} (known: {known})") from None


def names() -> list[str]:
    return sorted(_REGISTRY)


def _require_text(spec: dict, key: str, where: str) -> str:
    value = spec.get(key)
    if not isinstance(value, str):
        raise PatchError(f"{where}: operation {spec.get('op')!r} needs a '{key}' string")
    return value


@dataclass
class Operation:
    name: ClassVar[str] = ""
    needs_anchor: ClassVar[bool] = True

    @classmethod
    def from_spec(cls, spec: dict, where: str) -> "Operation":
        raise NotImplementedError

    def apply(self, source: str, anchor: Anchor | None, where: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _edit_matches(source: str, matches, render) -> str:
        # last match first, so earlier offsets stay valid
        for match in reversed(matches):
            values = {"match": match.group(0), **{k: v or "" for k, v in match.groupdict().items()}}
            source = source[:match.start()] + render(match, values) + source[match.end():]
        return source


@register("replace")
@dataclass
class Replace(Operation):
    with_: str

    @classmethod
    def from_spec(cls, spec: dict, where: str) -> "Replace":
        return cls(with_=_require_text(spec, "with", where))

    def apply(self, source: str, anchor: Anchor, where: str) -> str:
        matches = anchor.resolve(source, where)
        return self._edit_matches(source, matches, lambda m, v: substitute(self.with_, v))


@register("insert")
@dataclass
class Insert(Operation):
    text: str
    where_: str

    @classmethod
    def from_spec(cls, spec: dict, where: str) -> "Insert":
        position = spec.get("where", "after")
        if position not in ("before", "after"):
            raise PatchError(f"{where}: 'where' must be 'before' or 'after', got {position!r}")
        return cls(text=_require_text(spec, "text", where), where_=position)

    def apply(self, source: str, anchor: Anchor, where: str) -> str:
        matches = anchor.resolve(source, where)

        def render(match: re.Match[str], values: dict[str, str]) -> str:
            text = substitute(self.text, values)
            return f"{text}{match.group(0)}" if self.where_ == "before" else f"{match.group(0)}{text}"

        return self._edit_matches(source, matches, render)


@register("wrap")
@dataclass
class Wrap(Operation):
    prefix: str
    suffix: str

    @classmethod
    def from_spec(cls, spec: dict, where: str) -> "Wrap":
        prefix = spec.get("prefix", "")
        suffix = spec.get("suffix", "")
        if not isinstance(prefix, str) or not isinstance(suffix, str):
            raise PatchError(f"{where}: 'prefix' and 'suffix' must be strings")
        if not prefix and not suffix:
            raise PatchError(f"{where}: wrap needs at least one of 'prefix' or 'suffix'")
        return cls(prefix=prefix, suffix=suffix)

    def apply(self, source: str, anchor: Anchor, where: str) -> str:
        matches = anchor.resolve(source, where)

        def render(match: re.Match[str], values: dict[str, str]) -> str:
            return substitute(self.prefix, values) + match.group(0) + substitute(self.suffix, values)

        return self._edit_matches(source, matches, render)


@register("declare")
@dataclass
class Declare(Operation):
    needs_anchor: ClassVar[bool] = False
    text: str

    @classmethod
    def from_spec(cls, spec: dict, where: str) -> "Declare":
        include = spec.get("include")
        text = spec.get("text")
        if include is not None and text is not None:
            raise PatchError(f"{where}: declare takes either 'include' or 'text', not both")
        if isinstance(include, str):
            return cls(text=f"#include <{include}>")
        if isinstance(text, str):
            return cls(text=text)
        raise PatchError(f"{where}: declare needs an 'include' or a 'text' string")

    def apply(self, source: str, anchor: Anchor | None, where: str) -> str:
        if glsl.declares(source, self.text):
            return source
        return glsl.insert_after(source, glsl.declaration_line(source), self.text)
