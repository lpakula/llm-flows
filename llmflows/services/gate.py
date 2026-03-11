"""Gate evaluation — run shell commands to enforce step completion."""

import re
import subprocess
from pathlib import Path


def _interpolate(text: str, variables: dict) -> str:
    """Replace {{key}} placeholders with values from variables dict.

    Supports dotted keys like {{run.id}}, {{task.id}}, {{flow.name}}.
    """
    def replacer(match):
        key = match.group(1).strip()
        return variables.get(key, match.group(0))
    return re.sub(r"\{\{(\s*[\w.]+\s*)\}\}", replacer, text)


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
