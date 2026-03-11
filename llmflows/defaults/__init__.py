"""Package defaults -- used as fallback when no project override exists."""

from pathlib import Path

DEFAULTS_DIR = Path(__file__).parent


def get_defaults_dir() -> Path:
    return DEFAULTS_DIR
