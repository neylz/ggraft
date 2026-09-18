from __future__ import annotations

import json
from pathlib import Path

import click

from ggraft.cli.commands.common import load_config
from ggraft.config import Config
from ggraft.sources import McMeta


def _stamp(config: Config, version: str) -> dict[str, str]:
    return {"version": version, "repo": config.repo, "source": config.source}


def _read_stamp(path: Path) -> dict[str, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None   # unknown contents are stale contents
    return data if isinstance(data, dict) else None


def _write_stamp(path: Path, stamp: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")


@click.command()
@click.argument("version", required=False)
@click.option("--force", is_flag=True, help="refetch even if a base exists")
@click.option("--token", envvar="GITHUB_TOKEN", help="GitHub token [env: GITHUB_TOKEN]")
@click.option("-j", "--jobs", type=click.IntRange(min=1), default=8,
              show_default=True, help="parallel downloads")
@click.pass_obj
def pull(config_path: str | None, version: str | None, force: bool,
         token: str | None, jobs: int) -> None:
    """Fetch vanilla bases from mcmeta.

    VERSION defaults to base.version in ggraft.toml.
    """
    cfg = load_config(config_path)
    version = version or cfg.require_version()
    client = McMeta(cfg.repo, token=token)
    tag = client.tag_for(version)

    wanted = _stamp(cfg, version)
    held = _read_stamp(cfg.base_state)
    present = cfg.base_dir.is_dir() and any(cfg.base_dir.iterdir())

    if present and held == wanted and not force:
        click.echo(f"base already present at {cfg.base_dir} (use --force to refetch)")
        return
    if present and held != wanted:
        was = held.get("version") if held else None
        click.echo(f"{cfg.base_dir} holds {was or 'an unrecorded base'}; replacing it")

    click.echo(f"listing {cfg.source} at {tag} ...")
    blobs = client.list_blobs(tag, cfg.source)
    click.echo(f"fetching {len(blobs)} file(s) into {cfg.base_dir} ...")

    client.download(tag, cfg.source, blobs, cfg.base_dir, workers=jobs)
    _write_stamp(cfg.base_state, wanted)
    click.echo(f"pulled {len(blobs)} file(s) from {cfg.repo}@{tag}")
