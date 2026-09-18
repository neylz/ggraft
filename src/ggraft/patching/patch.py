from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ggraft.errors import PatchError
from ggraft.patching import operations
from ggraft.patching.anchor import Anchor
from ggraft.patching.operations import Operation


@dataclass
class Injection:
    index: int
    op: Operation
    anchor: Anchor | None

    def describe(self, patch: str, target: str) -> str:
        return f"{patch}[{self.index}] -> {target}"

    def apply(self, source: str, patch: str, target: str) -> str:
        return self.op.apply(source, self.anchor, self.describe(patch, target))


@dataclass
class Patch:
    name: str
    path: Path
    targets: list[str]
    injections: list[Injection]
    exclude: list[str] = field(default_factory=list)

    def applies_to(self, target: str) -> bool:
        if any(fnmatch.fnmatch(target, pattern) for pattern in self.exclude):
            return False
        return any(fnmatch.fnmatch(target, pattern) for pattern in self.targets)


def _as_str_list(value, key: str, where: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise PatchError(f"{where}: '{key}' must be a string or a list of strings")


def load(path: Path) -> Patch:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PatchError(f"{path}: invalid TOML: {exc}") from exc
    except OSError as exc:
        raise PatchError(f"{path}: cannot read: {exc}") from exc

    name = raw.get("name", path.stem)
    if not isinstance(name, str):
        raise PatchError(f"{path}: 'name' must be a string")

    if "targets" not in raw:
        raise PatchError(f"{path}: patch declares no 'targets'")
    targets = _as_str_list(raw["targets"], "targets", str(path))
    exclude = _as_str_list(raw.get("exclude", []), "exclude", str(path)) if "exclude" in raw else []

    specs = raw.get("injection", [])
    if not isinstance(specs, list) or not specs:
        raise PatchError(f"{path}: patch declares no [[injection]] blocks")

    injections: list[Injection] = []
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            raise PatchError(f"{path}: injection {index} is not a table")
        where = f"{name}[{index}]"
        op_name = spec.get("op")
        if not isinstance(op_name, str):
            raise PatchError(f"{where}: injection needs an 'op'")
        op_cls = operations.get(op_name, where)
        op = op_cls.from_spec(spec, where)
        anchor = Anchor.from_spec(spec, where) if op_cls.needs_anchor else None
        injections.append(Injection(index=index, op=op, anchor=anchor))

    return Patch(name=name, path=path, targets=targets, injections=injections, exclude=exclude)


def load_all(directory: Path) -> list[Patch]:
    # sorted by path: patches stack in filename order
    if not directory.is_dir():
        raise PatchError(f"patch directory not found: {directory}")
    paths = sorted(directory.rglob("*.toml"))
    if not paths:
        raise PatchError(f"no patches (*.toml) found under {directory}")
    return [load(p) for p in paths]
