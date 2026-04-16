"""Configuration management for llmflows.

System-wide config lives in ~/.llmflows/config.toml.
Per-space config is discovered via .llmflows/ in each directory.
"""

import shutil
import tomllib
from pathlib import Path
from typing import Any, Optional


SYSTEM_DIR = Path.home() / ".llmflows"
SYSTEM_DB = SYSTEM_DIR / "llmflows.db"
SYSTEM_CONFIG = SYSTEM_DIR / "config.toml"

SPACE_DIR = ".llmflows"


VALID_STEP_TYPES = ("code", "chat", "shell", "manual")

KNOWN_AGENTS = [
    "cursor",
    "claude-code",
    "codex",
    "qwen",
    "pi",
]

KNOWN_LLM_PROVIDERS = [
    "openai",
    "anthropic",
    "google",
    "ollama",
]

AGENT_REGISTRY = {
    # -- CLI coding agents (step_type=code) --
    "cursor": {
        "type": "code",
        "label": "Cursor",
        "binary": "agent",
        "api_key_env": "CURSOR_API_KEY",
        "command": "agent -p -f \"<prompt>\"",
        "prompt_mode": "file",
        "output_format": "stream-json",
        "tiers": {"max": "claude-4.6-opus-max-thinking", "normal": "composer-2", "mini": "gemini-3-flash"},
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
        "type": "code",
        "label": "Claude Code",
        "binary": "claude",
        "api_key_env": "ANTHROPIC_API_KEY",
        "command": "claude -p \"<prompt>\"",
        "prompt_mode": "arg",
        "output_format": "stream-json",
        "tiers": {"max": "opus", "normal": "sonnet", "mini": "haiku"},
        "models": [
            "default",
            "sonnet", "opus", "haiku",
            "claude-sonnet-4.6", "claude-opus-4.6",
            "claude-sonnet-4.5", "claude-opus-4.5",
        ],
    },
    "codex": {
        "type": "code",
        "label": "Codex",
        "binary": "codex",
        "api_key_env": "OPENAI_API_KEY",
        "command": "codex exec --json \"<prompt>\"",
        "prompt_mode": "arg",
        "output_format": "json",
        "tiers": {"max": "gpt-5.4", "normal": "gpt-5.4", "mini": "gpt-5.3-codex-spark"},
        "models": [
            "gpt-5.4", "gpt-5.3-codex-spark",
        ],
    },
    "qwen": {
        "type": "code",
        "label": "Qwen Code",
        "binary": "qwen",
        "api_key_env": "DASHSCOPE_API_KEY",
        "command": "qwen -p \"<prompt>\" -y --output-format stream-json",
        "prompt_mode": "arg",
        "output_format": "stream-json",
        "tiers": {"max": "default", "normal": "default", "mini": "default"},
        "models": [
            "default",
        ],
    },
    "pi": {
        "type": "code",
        "label": "Pi",
        "binary": "pi",
        "api_key_env": "PI_API_KEY",
        "command": "pi -p \"<prompt>\" --mode json",
        "prompt_mode": "arg",
        "output_format": "stream-json",
        "tiers": {"max": "anthropic/claude-opus-4-5", "normal": "anthropic/claude-sonnet-4-5", "mini": "anthropic/claude-haiku-4-5"},
        "models": [
            "anthropic/claude-opus-4-5",
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-haiku-4-5",
            "openai/gpt-4o",
            "openai/o3",
            "openai/o4-mini",
            "google/gemini-2.5-pro",
            "google/gemini-2.5-flash",
            "xai/grok-3",
            "xai/grok-3-mini",
            "mistral/mistral-large",
            "groq/llama-3.3-70b",
        ],
    },
    # -- Chat/LLM providers (step_type=chat, manual) --
    "openai": {
        "type": "chat",
        "label": "OpenAI",
        "api_key_env": "OPENAI_API_KEY",
        "supports_tools": ["web_search"],
        "tiers": {"max": "gpt-4o", "normal": "gpt-4o-mini", "mini": "gpt-4o-mini"},
    },
    "anthropic": {
        "type": "chat",
        "label": "Anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "supports_tools": ["web_search"],
        "tiers": {"max": "claude-sonnet-4-20250514", "normal": "claude-sonnet-4-20250514", "mini": "claude-haiku-3-5-20241022"},
    },
    "google": {
        "type": "chat",
        "label": "Google",
        "api_key_env": "GOOGLE_API_KEY",
        "supports_tools": ["web_search"],
        "tiers": {"max": "gemini-2.5-pro", "normal": "gemini-2.5-flash", "mini": "gemini-2.5-flash"},
    },
    "ollama": {
        "type": "chat",
        "label": "Ollama",
        "api_key_env": "OLLAMA_HOST",
        "supports_tools": [],
        "tiers": {"max": "llama3.1:70b", "normal": "llama3.1:8b", "mini": "llama3.1:8b"},
    },
}

KNOWN_MODELS = list({m for reg in AGENT_REGISTRY.values() for m in reg.get("models", [])})

_DEFAULTS_FILE = Path(__file__).parent / "defaults" / "config.toml"


def _load_defaults() -> dict[str, Any]:
    """Load the bundled defaults/config.toml as the canonical default config."""
    try:
        with open(_DEFAULTS_FILE, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


DEFAULT_CONFIG = _load_defaults()


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
                if isinstance(val, bool):
                    lines.append(f"{key} = {str(val).lower()}")
                elif isinstance(val, str):
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


def resolve_alias(session, alias_type: str, alias_name: str = "normal") -> tuple[str, str]:
    """Look up (agent, model) for a type + alias tier.

    Falls back to the first matching agent's default tiers from AGENT_REGISTRY.
    """
    from .db.models import AgentAlias
    alias = session.query(AgentAlias).filter_by(type=alias_type, name=alias_name).first()
    if alias:
        return alias.agent, alias.model
    for agent_key, reg in AGENT_REGISTRY.items():
        if reg.get("type") != alias_type:
            continue
        tiers = reg.get("tiers", {})
        if alias_name in tiers:
            return agent_key, tiers[alias_name]
    raise ValueError(f"Alias '{alias_name}' not found for type '{alias_type}'")


def infer_step_type(agent: str) -> str:
    """Derive step_type from agent's registry type. Returns 'code' or 'chat'."""
    reg = AGENT_REGISTRY.get(agent, {})
    return reg.get("type", "code")


def find_space_dir(start_path: Optional[Path] = None) -> Optional[Path]:
    """Find .llmflows/ directory by walking up from start_path."""
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()
    while current != current.parent:
        space_dir = current / SPACE_DIR
        if space_dir.is_dir():
            return space_dir
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


def is_git_repo(path: Optional[Path] = None) -> bool:
    """Check whether the given path is inside a git repository."""
    return get_repo_root(path) is not None
