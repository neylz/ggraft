from __future__ import annotations

from pathlib import Path

from ggraft import config as config_module
from ggraft.config import Config


def load_config(config_path: str | None) -> Config:
    return config_module.load(Path(config_path).resolve() if config_path else None)
