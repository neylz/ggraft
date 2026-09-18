from __future__ import annotations

from pathlib import Path

import click

from ggraft.config import CONFIG_NAME

STARTER = '''# ggraft project configuration
[base]
version = "{version}"
dir     = ".ggraft/base"
source  = "assets/minecraft/shaders"

[patches]
dir = "patches"

[output]
dir    = "assets/minecraft/shaders"
header = true
'''


@click.command()
@click.argument("version", required=False)
@click.option("--force", is_flag=True, help="overwrite an existing file")
def init(version: str | None, force: bool) -> None:
    """Write a starter ggraft.toml.

    VERSION is recorded as base.version.
    """
    destination = Path.cwd() / CONFIG_NAME
    if destination.exists() and not force:
        raise click.ClickException(
            f"{CONFIG_NAME} already exists here (use --force to overwrite)"
        )
    destination.write_text(STARTER.format(version=version or "26.3"), encoding="utf-8")
    click.echo(f"wrote {destination}")
