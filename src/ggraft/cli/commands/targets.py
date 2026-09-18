from __future__ import annotations

import click

from ggraft.cli.commands.common import load_config
from ggraft.patching import engine, patch as patch_module


@click.command()
@click.option("-t", "--target", "filters", multiple=True, metavar="GLOB",
              help="filter by glob (repeatable)")
@click.pass_obj
def targets(config_path: str | None, filters: tuple[str, ...]) -> None:
    """Show which patches hit which targets."""
    cfg = load_config(config_path)
    patches = patch_module.load_all(cfg.patch_dir)

    click.echo(f"{len(patches)} patch(es) in {cfg.patch_dir}:")
    for item in patches:
        click.echo(f"  {item.name:<24} {len(item.injections)} injection(s)"
                   f"  <- {item.path.name}")
    click.echo()
    for item in engine.plan(cfg, patches, only=list(filters) or None):
        click.echo(f"  {item.target:<38} {', '.join(item.patch_names)}")
