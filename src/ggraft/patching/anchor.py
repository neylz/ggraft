from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from ggraft.errors import AmbiguousInjection, PatchError, UnresolvedInjection

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def occurrence_of(spec: dict, where: str) -> int | None:
    occurrence = spec.get("occurrence")
    if occurrence is not None and (not isinstance(occurrence, int) or occurrence < 1):
        raise PatchError(f"{where}: 'occurrence' must be a positive integer (1-based)")
    return occurrence


def substitute(template: str, values: dict[str, str]) -> str:
    # unknown placeholders stay verbatim: a GLSL body is not a format string
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


@dataclass(frozen=True)
class Anchor:
    pattern: str
    regex: bool = False
    multiline: bool = False
    occurrence: int | None = None
    every: bool = False

    @classmethod
    def from_spec(cls, spec: dict, where: str) -> "Anchor":
        pattern = spec.get("match")
        if not isinstance(pattern, str) or not pattern:
            raise PatchError(f"{where}: this operation needs a non-empty 'match' anchor")
        occurrence = occurrence_of(spec, where)
        every = bool(spec.get("every", False))
        if every and occurrence is not None:
            raise PatchError(f"{where}: use either 'every' or 'occurrence', not both")
        anchor = cls(
            pattern=pattern,
            regex=bool(spec.get("regex", False)),
            multiline=bool(spec.get("multiline", False)),
            occurrence=occurrence,
            every=every,
        )
        anchor.compile(where)   # a malformed anchor fails at load, not mid-build
        return anchor

    def compile(self, where: str = "") -> Pattern[str]:
        # DOTALL only: literal text spanning lines already works, multiline is
        # about letting a single {placeholder} (or a regex .) cross them
        flags = re.MULTILINE | (re.DOTALL if self.multiline else 0)
        parts: list[str] = []
        if not self.regex:
            cursor = 0
            for found in PLACEHOLDER.finditer(self.pattern):
                parts.append(re.escape(self.pattern[cursor:found.start()]))
                parts.append(f"(?P<{found.group(1)}>.+?)")
                cursor = found.end()
            parts.append(re.escape(self.pattern[cursor:]))
        try:
            return re.compile(self.pattern if self.regex else "".join(parts), flags)
        except re.error as exc:
            subject = "regex" if self.regex else "anchor"
            prefix = f"{where}: " if where else ""
            raise PatchError(f"{prefix}{subject} {self.pattern!r} cannot be compiled: {exc}") from exc

    def resolve(self, source: str, where: str) -> list[re.Match[str]]:
        matches = list(self.compile(where).finditer(source))
        if not matches:
            raise UnresolvedInjection(where, f"anchor matched nothing: {self.pattern!r}")
        if self.every:
            return matches
        if self.occurrence is not None:
            if self.occurrence > len(matches):
                raise UnresolvedInjection(
                    where,
                    f"anchor asked for occurrence {self.occurrence} "
                    f"but matched {len(matches)} time(s): {self.pattern!r}",
                )
            return [matches[self.occurrence - 1]]
        if len(matches) > 1:
            lines = [source.count("\n", 0, m.start()) + 1 for m in matches]
            raise AmbiguousInjection(
                where,
                f"anchor matched {len(matches)} times (lines {lines}): {self.pattern!r}."
                " add 'occurrence = N' or 'every = true'",
            )
        return matches
