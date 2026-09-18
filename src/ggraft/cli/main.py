from __future__ import annotations

import errno
import os
import sys

import click

from ggraft import __version__
from ggraft.cli.commands import COMMANDS
from ggraft.config import CONFIG_NAME
from ggraft.errors import GgraftError

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 100}


# turns GgraftError into Click error reporting, so commands need not catch
class GgraftGroup(click.Group):
    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except GgraftError as exc:
            raise click.ClickException(str(exc)) from exc


@click.group(cls=GgraftGroup, context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, "-V", "--version", prog_name="ggraft")
@click.option("-c", "--config", "config_path",
              type=click.Path(dir_okay=False),
              help=f"path to {CONFIG_NAME} (default: search upwards)")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None) -> None:
    """Declarative injection patches for vanilla Minecraft shaders."""
    ctx.obj = config_path


for _command in COMMANDS:
    cli.add_command(_command)


# `| head` closing the pipe: EPIPE on POSIX, EINVAL from the flush on Windows
def _is_broken_pipe(exc: OSError) -> bool:
    if isinstance(exc, BrokenPipeError):
        return True
    return sys.platform == "win32" and exc.errno == errno.EINVAL


def main() -> None:
    try:
        cli()
    except OSError as exc:
        if not _is_broken_pipe(exc):
            raise
        # Redirect stdout so the shutdown flush cannot fail too. Exit 0: a
        # closed pipe is not an error and would otherwise trip `set -e`.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
