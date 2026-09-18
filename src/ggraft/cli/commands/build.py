from __future__ import annotations

import click

from ggraft.cli.commands.common import load_config
from ggraft.errors import TargetError
from ggraft.patching import engine, patch as patch_module


@click.command()
@click.option("-t", "--target", "targets", multiple=True, metavar="GLOB",
              help="only build targets matching this glob (repeatable)")
@click.option("--check", is_flag=True,
              help="do not write; exit non-zero if output would change")
@click.pass_obj
def build(config_path: str | None, targets: tuple[str, ...], check: bool) -> None:
    """Apply patches to the base."""
    cfg = load_config(config_path)
    patches = patch_module.load_all(cfg.patch_dir)
    plans = engine.plan(cfg, patches, only=list(targets) or None)
    if not plans:
        raise TargetError("no targets matched any patch")

    # A filtered build cannot tell what is stale, so it never prunes.
    report = engine.run(cfg, plans, write=not check, prune=not targets)
    changed = [r for r in report.results if r.changed]

    for result in report.results:
        mark = "*" if result.changed else " "
        click.echo(f" {mark} {result.target:<38} {result.injections:>2} injection(s)"
                   f"  [{', '.join(result.patches)}]")
    for target in report.pruned:
        click.echo(f" - {target:<38} removed (no longer targeted)")

    verb = "would patch" if check else "patched"
    summary = f"{verb} {len(report.results)} shader(s), {len(changed)} changed"
    if report.pruned:
        summary += f", {len(report.pruned)} pruned"
    click.echo("\n" + summary)

    if check and changed:
        raise SystemExit(1)
