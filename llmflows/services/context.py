"""Context service -- renders step prompts and collects artifacts."""

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from jinja2 import ChainableUndefined, Environment, TemplateError

from ..defaults import get_defaults_dir

logger = logging.getLogger(__name__)

DEFAULTS_DIR = get_defaults_dir()

RESULT_FILE = "_result.md"
INBOX_FILE = "inbox.md"
HITL_FILE = "hitl.md"

RESULT_FILE_LIMIT = 50_000
ARTIFACT_FILE_LIMIT = 20_000
TOTAL_ARTIFACTS_BUDGET = 120_000

BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg",
    ".mp4", ".webm", ".mov", ".avi", ".mp3", ".wav", ".ogg",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe",
})

class ContextService:
    def __init__(self, space_dir: Path):
        """Initialize with the .llmflows/ directory in a space or worktree."""
        self.space_dir = space_dir

    def render_step_instructions(self, context: dict) -> str:
        """Render step_start.md as the prompt for a single step agent."""
        template_file = DEFAULTS_DIR / "step_start.md"
        if not template_file.exists():
            return ""
        try:
            env = Environment(autoescape=False)
            template = env.from_string(template_file.read_text())
            return template.render(context)
        except TemplateError:
            logger.exception("Failed to render step_start.md template")
            return ""

    def render_post_run_step(self, context: dict) -> str:
        """Render step_post_run.md for the post-run analysis step."""
        template_file = DEFAULTS_DIR / "step_post_run.md"
        if not template_file.exists():
            return ""
        try:
            env = Environment(autoescape=False, undefined=ChainableUndefined)
            template = env.from_string(template_file.read_text())
            return template.render(context)
        except TemplateError:
            logger.exception("Failed to render step_post_run.md template")
            return ""

    @staticmethod
    def collect_artifacts(artifacts_dir: Path) -> list[dict]:
        """Collect artifacts from completed steps.

        Prioritises ``_result.md`` per step (higher char limit) and includes
        remaining files up to a total budget.  Returns a list of dicts:
          - position: int
          - step_name: str
          - result: str | None  (contents of _result.md if present)
          - files: list of {name, content}
        """
        if not artifacts_dir.exists():
            return []

        try:
            step_dirs = sorted(
                d for d in artifacts_dir.iterdir()
                if d.is_dir() and d.name[0:2].isdigit()
            )
        except (PermissionError, OSError):
            return []

        artifacts: list[dict] = []
        budget_remaining = TOTAL_ARTIFACTS_BUDGET

        for step_dir in step_dirs:
            parts = step_dir.name.split("-", 1)
            try:
                position = int(parts[0])
            except (ValueError, IndexError):
                continue
            step_name = parts[1] if len(parts) > 1 else step_dir.name

            result_text: str | None = None
            result_path = step_dir / RESULT_FILE
            if result_path.exists():
                try:
                    raw = result_path.read_text(errors="replace")
                    if len(raw) > RESULT_FILE_LIMIT:
                        raw = raw[:RESULT_FILE_LIMIT] + "\n... (truncated)"
                    result_text = raw
                    budget_remaining -= len(result_text)
                except (PermissionError, OSError):
                    pass

            files: list[dict] = []
            try:
                for f in sorted(step_dir.iterdir()):
                    if not f.is_file() or f.name == RESULT_FILE:
                        continue
                    if f.suffix.lower() in BINARY_EXTENSIONS:
                        files.append({"name": f.name, "content": "(binary file, not shown)"})
                        continue
                    if budget_remaining <= 0:
                        files.append({"name": f.name, "content": "(budget exceeded, skipped)"})
                        continue
                    try:
                        content = f.read_text(errors="replace")
                        limit = min(ARTIFACT_FILE_LIMIT, budget_remaining)
                        if len(content) > limit:
                            content = content[:limit] + "\n... (truncated)"
                        files.append({"name": f.name, "content": content})
                        budget_remaining -= len(content)
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError):
                pass

            if result_text or files:
                artifacts.append({
                    "position": position,
                    "step_name": step_name,
                    "path": str(step_dir),
                    "result": result_text,
                    "files": files,
                })

        return artifacts

    @staticmethod
    def read_summary_artifact(artifacts_dir: Path, **_kwargs) -> str:
        """Read the summary.md file from the artifacts root, if it exists."""
        summary_file = artifacts_dir / "summary.md"
        if not summary_file.exists():
            return ""
        try:
            return summary_file.read_text().strip()
        except (PermissionError, OSError):
            return ""

    @staticmethod
    def read_inbox_message(artifacts_dir: Path) -> str:
        """Read inbox.md from the artifacts root, if it exists."""
        inbox_file = artifacts_dir / INBOX_FILE
        if not inbox_file.exists():
            return ""
        try:
            return inbox_file.read_text().strip()
        except (PermissionError, OSError):
            return ""

    @staticmethod
    def parse_inbox_message(text: str) -> tuple[str, str]:
        """Parse inbox.md text into (title, body).

        If the first non-empty line is a markdown heading (# ...), use it as
        title with the remainder as body.  Otherwise use the first line as
        title and the rest as body.
        """
        if not text:
            return ("", "")
        lines = text.split("\n")
        first_line = ""
        first_idx = 0
        for i, line in enumerate(lines):
            if line.strip():
                first_line = line.strip()
                first_idx = i
                break
        if not first_line:
            return ("", "")
        if first_line.startswith("#"):
            title = first_line.lstrip("#").strip()
        else:
            title = first_line
        body = "\n".join(lines[first_idx + 1:]).strip()
        return (title, body)

    @staticmethod
    def read_last_step_result(artifacts_dir: Path) -> str:
        """Read _result.md from the last (highest-numbered) step directory."""
        if not artifacts_dir.exists():
            return ""
        try:
            step_dirs = sorted(
                (d for d in artifacts_dir.iterdir()
                 if d.is_dir() and d.name[0:2].isdigit()),
                key=lambda d: d.name,
            )
        except (PermissionError, OSError):
            return ""
        for step_dir in reversed(step_dirs):
            result_path = step_dir / RESULT_FILE
            if result_path.exists():
                try:
                    return result_path.read_text(errors="replace").strip()
                except (PermissionError, OSError):
                    continue
        return ""

    @staticmethod
    def read_improvement(artifacts_dir: Path) -> str:
        """Read improvement.md from the artifacts root, if it exists."""
        f = artifacts_dir / "improvement.md"
        if not f.exists():
            return ""
        try:
            return f.read_text(errors="replace").strip()
        except (PermissionError, OSError):
            return ""

    @staticmethod
    def read_flow_json(artifacts_dir: Path) -> dict | None:
        """Read flow.json from the artifacts root, if it exists."""
        import json
        f = artifacts_dir / "flow.json"
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text())
            if isinstance(data, dict) and data.get("steps"):
                return data
        except (json.JSONDecodeError, PermissionError, OSError):
            pass
        return None

    @staticmethod
    def get_memory_dir(flow_dir: Path) -> Path:
        """Return the memory directory for a flow: ``flow_dir/memory/``."""
        return flow_dir / "memory"

    @staticmethod
    def list_memory_files(flow_dir: Path) -> list[dict]:
        """Return ``[{name, content}]`` for every file in the memory directory."""
        mem_dir = flow_dir / "memory"
        if not mem_dir.is_dir():
            return []
        files: list[dict] = []
        try:
            for f in sorted(mem_dir.iterdir()):
                if not f.is_file():
                    continue
                if f.suffix.lower() in BINARY_EXTENSIONS:
                    continue
                try:
                    content = f.read_text(errors="replace").strip()
                    if content:
                        files.append({"name": f.name, "content": content})
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass
        return files

    @staticmethod
    def read_rejected_proposals(flow_dir: Path) -> str:
        """Read the rejected-proposals.md file content as a single string."""
        f = flow_dir / "memory" / "rejected-proposals.md"
        if not f.exists():
            return ""
        try:
            return f.read_text(errors="replace").strip()
        except (PermissionError, OSError):
            return ""

    @staticmethod
    def write_memory_file(flow_dir: Path, filename: str, content: str) -> None:
        """Write (or overwrite) a single memory file."""
        flow_dir.mkdir(parents=True, exist_ok=True)
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / filename).write_text(content)

    @staticmethod
    def delete_memory_file(flow_dir: Path, filename: str) -> bool:
        """Delete a single memory file.  Returns True if a file was actually removed."""
        f = flow_dir / "memory" / filename
        if f.exists():
            f.unlink()
            return True
        return False

    @staticmethod
    def append_memory(flow_dir: Path, entry: str) -> None:
        """Append an entry to the rejected-proposals memory file."""
        flow_dir.mkdir(parents=True, exist_ok=True)
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        f = mem_dir / "rejected-proposals.md"
        existing = ""
        if f.exists():
            try:
                existing = f.read_text(errors="replace")
            except (PermissionError, OSError):
                pass
        separator = "\n\n---\n\n" if existing.strip() else ""
        f.write_text(existing + separator + entry + "\n")

    @staticmethod
    def _safe_flow_dir(flow_name: str) -> str:
        """Return a filesystem-safe directory name for a flow."""
        import re
        slug = flow_name.strip().lower().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9._-]", "", slug)
        return slug or "_default"

    @staticmethod
    def get_flow_dir(project_path: Path, flow_name: str = "") -> Path:
        """Return the persistent flow directory: .llmflows/<flow_name>/

        Useful for data that should persist across runs of the same flow.
        """
        flow_dir = ContextService._safe_flow_dir(flow_name) if flow_name else "_default"
        return project_path / ".llmflows" / flow_dir

    @staticmethod
    def get_artifacts_dir(project_path: Path, run_id: str, flow_name: str = "") -> Path:
        """Return the artifacts directory for a run, always under the main space root.

        Layout: .llmflows/<flow_name>/runs/<run_id>/artifacts/
        """
        return ContextService.get_flow_dir(project_path, flow_name) / "runs" / run_id / "artifacts"

    @staticmethod
    def step_dir_name(position: int, step_name: str) -> str:
        """Build a filesystem-safe artifact directory name for a step."""
        return f"{position:02d}-{step_name.replace(' ', '-').lower()}"


_GENERATE_SYSTEM_PROMPT = """\
You are a flow definition editor. You receive a current flow definition (JSON), \
a list of proposed improvements, and the user's selection of which ones to apply. \
Your job is to apply ONLY the selected improvements to the flow and return the \
updated flow JSON.

Rules:
- Start from the current flow JSON exactly as provided.
- Apply only the improvements the user selected — leave everything else unchanged.
- Do NOT rewrite, reorganize, or change anything not covered by the selection.
- Increment the "version" field by 1.
- Return ONLY the complete flow JSON — no markdown fences, no explanation, no commentary.\
"""


def generate_flow_from_improvements(
    current_flow: dict,
    improvements: str,
    selection: str = "",
) -> dict:
    """Call pi CLI to generate an updated flow.json from improvements.

    Takes the current flow export, the full improvement.md text, and an
    optional natural-language selection (empty means apply all).
    Returns the resulting flow dict.

    Raises ValueError if the LLM output is not valid flow JSON.
    """
    from .chat import resolve_chat_model, resolve_chat_env

    model = resolve_chat_model(tier="normal")
    env = resolve_chat_env()
    env["NODE_PATH"] = str(
        Path(__file__).resolve().parent.parent.parent
        / ".llmflows"
        / "node_modules"
    )

    selection_text = selection.strip() if selection else "Apply all improvements."
    prompt_text = (
        "## Current flow definition\n\n"
        f"```json\n{json.dumps(current_flow, indent=2)}\n```\n\n"
        "## Proposed improvements\n\n"
        f"{improvements}\n\n"
        f"## User selection\n\n{selection_text}\n\n"
        "Apply the selected improvements to the current flow. "
        "Return ONLY the updated JSON."
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False
    ) as f:
        f.write(prompt_text)
        prompt_file = f.name

    try:
        cmd = [
            "pi",
            "-p",
            "--system-prompt", _GENERATE_SYSTEM_PROMPT,
            "--mode", "text",
            f"@{prompt_file}",
        ]
        if model:
            cmd.extend(["--model", model])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd=str(Path.home()),
        )

        if proc.returncode != 0:
            logger.warning("pi generate call failed: %s", proc.stderr[:300])
            raise ValueError("LLM call failed")

        return _parse_flow_json_response(proc.stdout)

    except subprocess.TimeoutExpired:
        raise ValueError("LLM call timed out")
    except FileNotFoundError:
        raise ValueError("pi CLI not available")
    finally:
        os.unlink(prompt_file)


def _parse_flow_json_response(output: str) -> dict:
    """Extract and validate a flow JSON object from LLM output."""
    text = output.strip()

    # Strip markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    # Find the outermost JSON object
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM response")

    depth = 0
    end = start
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in LLM response: {e}")

    if not isinstance(data, dict) or not data.get("steps"):
        raise ValueError("LLM response missing required 'steps' field")

    return data
