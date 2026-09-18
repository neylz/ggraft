from ggraft.cli.commands.build import build
from ggraft.cli.commands.init import init
from ggraft.cli.commands.pull import pull
from ggraft.cli.commands.targets import targets

COMMANDS = [init, pull, build, targets]

__all__ = [
    "COMMANDS",
    "build",
    "init",
    "pull",
    "targets"
]
