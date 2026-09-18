from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ggraft.errors import ConfigError

CONFIG_NAME = "ggraft.toml"

DEFAULT_SOURCE = "assets/minecraft/shaders"
DEFAULT_BASE_DIR = ".ggraft/base"
DEFAULT_PATCH_DIR = "patches"
DEFAULT_REPO = "misode/mcmeta"


@dataclass
class Config:
    root: Path
    version: str | None
    base_dir: Path
    source: str
    patch_dir: Path
    output_dir: Path
    header: bool
    repo: str

    @property
    def manifest(self) -> Path:
        return self.root / ".ggraft" / "manifest.json"

    @property
    def base_state(self) -> Path:
        return self.root / ".ggraft" / "base.json"

    def require_version(self) -> str:
        if not self.version:
            raise ConfigError(
                "no Minecraft version configured; set base.version in ggraft.toml "
                "or pass one on the command line"
            )
        return self.version


def find(start: Path | None = None) -> Path:
    """Locate ggraft.toml in ``start`` or any parent directory."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(f"no {CONFIG_NAME} found in {current} or any parent directory")


def load(path: Path | None = None) -> Config:
    path = path or find()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read: {exc}") from exc

    root = path.parent
    base = raw.get("base", {})
    patches = raw.get("patches", {})
    output = raw.get("output", {})

    if not isinstance(base, dict) or not isinstance(patches, dict) or not isinstance(output, dict):
        raise ConfigError(f"{path}: [base], [patches] and [output] must be tables")

    if "dir" not in output:
        raise ConfigError(f"{path}: output.dir is required")

    def resolve(value: str) -> Path:
        return (root / value).resolve()

    return Config(
        root=root,
        version=base.get("version"),
        base_dir=resolve(base.get("dir", DEFAULT_BASE_DIR)),
        source=base.get("source", DEFAULT_SOURCE).strip("/"),
        patch_dir=resolve(patches.get("dir", DEFAULT_PATCH_DIR)),
        output_dir=resolve(output["dir"]),
        header=bool(output.get("header", True)),
        repo=base.get("repo", DEFAULT_REPO),
    )
