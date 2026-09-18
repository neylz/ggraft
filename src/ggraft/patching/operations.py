from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, ClassVar

from ggraft import glsl
from ggraft.errors import AmbiguousInjection, PatchError, UnresolvedInjection
from ggraft.patching.anchor import Anchor, occurrence_of, substitute

_REGISTRY: dict[str, type["Operation"]] = {}

_POINTS = ("HEAD", "TAIL", "RETURN", "INVOKE", "BEFORE", "AFTER")


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
    text: str = ""
    include: str = ""

    @classmethod
    def from_spec(cls, spec: dict, where: str) -> "Declare":
        include = spec.get("include")
        text = spec.get("text")
        if include is not None and text is not None:
            raise PatchError(f"{where}: declare takes either 'include' or 'text', not both")
        if isinstance(include, str):
            return cls(include=include)
        if isinstance(text, str):
            return cls(text=text)
        raise PatchError(f"{where}: declare needs an 'include' or a 'text' string")

    def line(self) -> str:
        return glsl.include_line(self.include) if self.include else self.text

    def apply(self, source: str, anchor: Anchor | None, where: str) -> str:
        text = self.line()
        if glsl.declares(source, text):
            return source
        return glsl.insert_after(source, glsl.declaration_line(source), text)


def _rest_of_line(source: str, position: int) -> str:
    end = source.find("\n", position)
    return source[position:] if end < 0 else source[position:end]


def _start_of_line(source: str, position: int) -> int:
    return source.rfind("\n", 0, position) + 1


def _folded(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


@register("function")
@dataclass
class FunctionInject(Operation):
    """Mixin-style injection"""

    needs_anchor: ClassVar[bool] = False
    function: str
    point: str
    text: str
    occurrence: int | None = None
    call: str = ""
    where_: str = "before"

    @classmethod
    def from_spec(cls, spec: dict, where: str) -> "FunctionInject":
        name = spec.get("function")
        if not isinstance(name, str) or not name:
            raise PatchError(f"{where}: function needs a 'function' name")

        point = spec.get("at", "HEAD")
        if point not in _POINTS:
            raise PatchError(
                f"{where}: 'at' must be one of {', '.join(_POINTS)}, got {point!r}"
            )

        call = spec.get("call")
        position = spec.get("where", "before")
        if point == "INVOKE":
            if not isinstance(call, str) or not call:
                raise PatchError(f"{where}: INVOKE needs a 'call' naming the function called")
            if position not in ("before", "after"):
                raise PatchError(
                    f"{where}: 'where' must be 'before' or 'after', got {position!r}"
                )
        elif "call" in spec or "where" in spec:
            raise PatchError(f"{where}: 'call' and 'where' only apply to at = \"INVOKE\"")

        return cls(
            function=name,
            point=point,
            text=_require_text(spec, "text", where),
            occurrence=occurrence_of(spec, where),
            call=call or "",
            where_=position,
        )

    def _definition(self, source: str, where: str) -> glsl.Function:
        found = glsl.find_functions(source, self.function)
        if not found:
            raise UnresolvedInjection(where, f"no function named {self.function!r} in this shader")

        if self.occurrence is not None:
            if self.occurrence > len(found):
                raise UnresolvedInjection(
                    where,
                    f"asked for occurrence {self.occurrence} of {self.function!r} "
                    f"but it is defined {len(found)} time(s)",
                )
            target = found[self.occurrence - 1]
        elif len(found) > 1:
            lines = [source.count("\n", 0, f.start) + 1 for f in found]
            raise AmbiguousInjection(
                where,
                f"{self.function!r} is defined {len(found)} times (lines {lines})."
                " add 'occurrence = N'",
            )
        else:
            target = found[0]

        if target.close_brace < 0:
            raise UnresolvedInjection(where, f"the body of {self.function!r} is never closed")
        return target

    def _invocations(self, source: str, target: glsl.Function, where: str) -> list[tuple[int, bool, str]]:
        calls = glsl.find_calls(source, target, self.call)
        if not calls:
            raise UnresolvedInjection(
                where, f"{self.function!r} contains no call to {self.call!r}"
            )

        sites = []
        for call in calls:
            start, end = glsl.statement_span(source, call, target.open_brace + 1)
            indent = glsl.line_indent(source, start)
            if self.where_ == "before":
                sites.append((start, False, indent))
            elif end < 0:
                raise UnresolvedInjection(
                    where,
                    f"the call to {self.call!r} opens a block instead of ending a "
                    'statement, so there is nothing to follow; use where = "before"',
                )
            else:
                sites.append((end, True, indent))
        return sites

    def _sites(self, source: str, target: glsl.Function, where: str) -> list[tuple[int, bool, str]]:
        """Each site as ``(offset, insert after it, indentation)``, in source order."""
        if self.point == "HEAD":
            return [(target.open_brace + 1, True, glsl.body_indent(source, target))]
        if self.point == "TAIL":
            return [(target.close_brace, False, glsl.body_indent(source, target))]
        if self.point == "BEFORE":
            # a whole declaration, so it takes the line above the signature
            start = _start_of_line(source, target.start)
            return [(start, False, glsl.line_indent(source, target.start))]
        if self.point == "AFTER":
            return [(target.close_brace + 1, True, glsl.line_indent(source, target.start))]
        if self.point == "RETURN":
            found = glsl.return_statements(source, target)
            if not found:
                raise UnresolvedInjection(
                    where,
                    f"{self.function!r} has no return statement; use at = \"TAIL\" instead",
                )
            return [(at, False, glsl.line_indent(source, at)) for at in found]
        return self._invocations(source, target, where)

    def apply(self, source: str, anchor: Anchor | None, where: str) -> str:
        target = self._definition(source, where)
        # last site first, so earlier offsets stay valid
        for site, after, indent in reversed(self._sites(source, target, where)):
            source = self._place(source, site, after, indent)
        return source

    def _place(self, source: str, site: int, after: bool, indent: str) -> str:
        """A line of its own, or inline when the statement shares a line."""
        block = "".join(
            f"{indent}{line}\n" if line.strip() else "\n" for line in self.text.splitlines()
        )
        if after:
            if _rest_of_line(source, site).strip():
                return source[:site] + " " + _folded(self.text) + source[site:]
            newline = source.find("\n", site)
            if newline < 0:                  # nothing follows: the file ends here
                return source + "\n" + block
            line_start = newline + 1
        else:
            line_start = _start_of_line(source, site)
            if source[line_start:site].strip():
                return source[:site] + _folded(self.text) + " " + source[site:]

        return source[:line_start] + block + source[line_start:]
