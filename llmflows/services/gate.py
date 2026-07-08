"""Gate & IF evaluation — run shell commands to enforce step completion / conditional inclusion."""

import logging
import re
import subprocess
from pathlib import Path

from ..utils.paths import space_local_path

logger = logging.getLogger(__name__)

# Template variables that hold filesystem paths and must be localized for the
# executing environment (host path → /workspace inside runner containers).
_PATH_VAR_KEYS = ("run.dir", "flow.dir", "step.dir", "attachment.dir")


def build_step_vars(base_vars: dict, space, flow_snapshot=None) -> dict:
    """Build template variables for gates, IFs, and step content rendering.

    Shared by the host orchestrator daemon and the in-container RunDaemon.
    Path-valued variables (``run.dir``, ``flow.dir``, ``step.dir``,
    ``attachment.dir``, ``space.dir``) are mapped through
    :func:`space_local_path` so they resolve inside runner containers.
    Flow snapshot variables never overwrite computed keys.
    """
    merged = dict(base_vars)
    for key in _PATH_VAR_KEYS:
        value = merged.get(key)
        if value:
            merged[key] = space_local_path(str(value))
    if space is not None and getattr(space, "path", None):
        merged["space.dir"] = space_local_path(str(space.path))
    flow_vars = {}
    if flow_snapshot and isinstance(flow_snapshot, dict):
        flow_vars = flow_snapshot.get("variables", {})
    for k, v in flow_vars.items():
        merged.setdefault(f"flow.{k}", v["value"])
        merged.setdefault(f"space.{k}", v["value"])
    return merged


def _interpolate(text: str, variables: dict) -> str:
    """Replace {{key}} placeholders with values from variables dict.

    Supports dotted keys like {{run.id}}, {{flow.name}}, {{hitl.response.0}}.
    Used for gate/IF commands where full Jinja2 is unnecessary.
    """
    def replacer(match):
        key = match.group(1).strip()
        return variables.get(key, match.group(0))
    return re.sub(r"\{\{([^}]+)\}\}", replacer, text)


def _to_nested(flat: dict) -> dict:
    """Convert flat dotted-key dict to nested dict for Jinja2.

    ``{"flow.ISSUE_NUMBER": "27", "run.id": "abc"}``
    → ``{"flow": {"ISSUE_NUMBER": "27"}, "run": {"id": "abc"}}``
    """
    nested: dict = {}
    for key, value in flat.items():
        parts = key.split(".")
        d = nested
        for part in parts[:-1]:
            if part not in d or not isinstance(d[part], dict):
                d[part] = {}
            d = d[part]
        d[parts[-1]] = value
    return nested


def render_step_content(text: str, variables: dict) -> str:
    """Render step content with Jinja2 (supports ``{% if %}``, ``{{ }}``).

    Variables arrive as a flat dotted-key dict and are converted to nested
    dicts so ``{% if flow.PR_NUMBER %}`` and ``{{flow.PR_NUMBER}}`` work.
    Undefined variables evaluate to empty string / falsy.
    """
    from jinja2 import ChainableUndefined, Environment

    nested = _to_nested(variables)
    env = Environment(autoescape=False, undefined=ChainableUndefined)
    try:
        template = env.from_string(text)
        return template.render(nested)
    except Exception:
        logger.warning("Jinja2 render failed for step content, falling back to simple interpolation", exc_info=True)
        return _interpolate(text, variables)


def evaluate_gates(
    gates: list[dict], cwd: Path, timeout: int = 60,
    variables: dict | None = None,
) -> list[dict]:
    """Evaluate a list of gates. Returns a list of failures (empty = all passed).

    Each gate is {"command": "...", "message": "..."}.
    A gate passes when the command exits 0.
    Supports {{variable}} interpolation in command and message.
    """
    variables = variables or {}
    failures = []
    for gate in gates:
        command = _interpolate(gate.get("command", ""), variables)
        message = _interpolate(gate.get("message", command), variables)
        if not command:
            continue
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd,
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                failures.append({
                    "message": message,
                    "command": command,
                    "exit_code": result.returncode,
                    "stderr": stderr[:500] if stderr else "",
                })
        except subprocess.TimeoutExpired:
            failures.append({
                "message": message,
                "command": command,
                "exit_code": -1,
                "stderr": f"Timed out after {timeout}s",
            })
        except Exception as e:
            failures.append({
                "message": message,
                "command": command,
                "exit_code": -1,
                "stderr": str(e),
            })
    return failures


def evaluate_ifs(
    ifs: list[dict], cwd: Path, timeout: int = 60,
    variables: dict | None = None,
) -> bool:
    """Evaluate IF conditions for a step. Returns True if the step should run.

    Each entry is {"command": "...", "message": "..."}.
    ALL commands must exit 0 for the step to be included.
    If any command exits non-zero, the step is skipped.
    Empty list or no commands → step always runs.
    """
    variables = variables or {}
    for entry in ifs:
        command = _interpolate(entry.get("command", ""), variables)
        if not command:
            continue
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd,
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0:
                return False
        except (subprocess.TimeoutExpired, Exception):
            return False
    return True
