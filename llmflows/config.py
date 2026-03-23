"""Configuration management for llmflows.

System-wide config lives in ~/.llmflows/config.toml.
Per-project config is discovered via .llmflows/ in each repo.
"""

import os
import shutil
import tomllib
from pathlib import Path
from typing import Any, Optional


SYSTEM_DIR = Path.home() / ".llmflows"
SYSTEM_DB = SYSTEM_DIR / "llmflows.db"
SYSTEM_CONFIG = SYSTEM_DIR / "config.toml"

PROJECT_DIR = ".llmflows"


KNOWN_AGENTS = [
    "cursor",
    "claude-code",
    "codex",
]

AGENT_REGISTRY = {
    "cursor": {
        "label": "Cursor",
        "binary": "agent",
        "command": "agent -p -f \"<prompt>\"",
        "prompt_mode": "file",
        "output_format": "stream-json",
        "models": [
            "auto",
            "claude-4.6-opus-high-thinking", "claude-4.6-opus-high",
            "claude-4.6-opus-max-thinking", "claude-4.6-opus-max",
            "claude-4.6-sonnet-medium-thinking", "claude-4.6-sonnet-medium",
            "claude-4.5-opus-high-thinking", "claude-4.5-opus-high",
            "claude-4.5-sonnet-thinking", "claude-4.5-sonnet",
            "claude-4-sonnet-thinking", "claude-4-sonnet",
            "gemini-3.1-pro", "gemini-3-pro", "gemini-3-flash",
            "gpt-5.4-high", "gpt-5.4-medium", "gpt-5.4-xhigh",
            "gpt-5.2", "gpt-5.2-high",
            "grok-4-20-thinking", "grok-4-20",
            "composer-2", "composer-2-fast", "composer-1.5",
        ],
    },
    "claude-code": {
        "label": "Claude Code",
        "binary": "claude",
        "command": "claude -p \"<prompt>\"",
        "prompt_mode": "arg",
        "output_format": "json",
        "models": [
            "default",
            "sonnet", "opus", "haiku",
            "claude-sonnet-4.6", "claude-opus-4.6",
            "claude-sonnet-4.5", "claude-opus-4.5",
        ],
    },
    "codex": {
        "label": "Codex",
        "binary": "codex",
        "command": "codex exec --json \"<prompt>\"",
        "prompt_mode": "arg",
        "output_format": "json",
        "models": [
            "gpt-5.4", "gpt-5.3-codex-spark",
        ],
    },
}

KNOWN_MODELS = list({m for reg in AGENT_REGISTRY.values() for m in reg["models"]})

_DEFAULTS_FILE = Path(__file__).parent / "defaults" / "config.toml"


def _load_defaults() -> dict[str, Any]:
    """Load the bundled defaults/config.toml as the canonical default config."""
    try:
        with open(_DEFAULTS_FILE, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def ensure_system_dir() -> Path:
    """Create ~/.llmflows/ and seed config.toml with defaults if missing."""
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    if not SYSTEM_CONFIG.exists():
        shutil.copy2(_DEFAULTS_FILE, SYSTEM_CONFIG)
    return SYSTEM_DIR


def load_system_config() -> dict[str, Any]:
    """Load global config from ~/.llmflows/config.toml, falling back to defaults."""
    defaults = _load_defaults()
    if SYSTEM_CONFIG.exists():
        try:
            with open(SYSTEM_CONFIG, "rb") as f:
                user_config = tomllib.load(f)
            merged = defaults.copy()
            for section, values in user_config.items():
                if section in merged and isinstance(merged[section], dict):
                    merged[section] = {**merged[section], **values}
                else:
                    merged[section] = values
            return merged
        except Exception:
            pass
    return defaults


def _write_config(config: dict[str, Any]) -> Path:
    """Write config dict to ~/.llmflows/config.toml."""
    lines = []
    for section, values in config.items():
        if isinstance(values, dict):
            lines.append(f"[{section}]")
            for key, val in values.items():
                if isinstance(val, str):
                    lines.append(f'{key} = "{val}"')
                else:
                    lines.append(f"{key} = {val}")
            lines.append("")
    SYSTEM_CONFIG.write_text("\n".join(lines))
    return SYSTEM_CONFIG


def save_system_config(config: dict[str, Any]) -> Path:
    """Save global config to ~/.llmflows/config.toml."""
    ensure_system_dir()
    return _write_config(config)


def get_github_token() -> Optional[str]:
    """Return a GitHub token from GITHUB_TOKEN env var or config.toml, in that order."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    config = load_system_config()
    token = config.get("github", {}).get("token", "")
    return token or None


def find_project_dir(start_path: Optional[Path] = None) -> Optional[Path]:
    """Find .llmflows/ directory by walking up from start_path."""
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()
    while current != current.parent:
        project_dir = current / PROJECT_DIR
        if project_dir.is_dir():
            return project_dir
        current = current.parent
    return None


def get_repo_root(start_path: Optional[Path] = None) -> Optional[Path]:
    """Get the git repo root for the given path."""
    import subprocess
    cwd = str(start_path or Path.cwd())
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None
