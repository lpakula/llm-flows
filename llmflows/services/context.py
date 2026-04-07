"""Context service -- renders step prompts and collects artifacts."""

import json
from pathlib import Path

from jinja2 import Environment, TemplateError

from ..defaults import get_defaults_dir

DEFAULTS_DIR = get_defaults_dir()

RESULT_FILE = "_result.md"

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

LOG_TAIL_LINES = 200
LOG_TAIL_MAX_CHARS = 30_000


def _parse_jsonl_log(raw: str, max_chars: int = LOG_TAIL_MAX_CHARS) -> str:
    """Extract human-readable text from a JSONL agent log."""
    parts: list[str] = []
    budget = max_chars

    for line in raw.splitlines():
        if budget <= 0:
            break
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        t = ev.get("type")

        if t == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    parts.append(c["text"].strip())

        elif t == "tool_call" and ev.get("subtype") == "started":
            tc = ev.get("tool_call", {})
            desc = _describe_tool_start(tc)
            if desc:
                parts.append(f"> {desc}")

        elif t == "tool_call" and ev.get("subtype") == "completed":
            tc = ev.get("tool_call", {})
            desc, output = _describe_tool_done(tc)
            if desc:
                parts.append(f"> {desc}")
            if output:
                trimmed = output[:2000] + "\n..." if len(output) > 2000 else output
                parts.append(trimmed)

        elif t == "result":
            dur = ev.get("duration_ms", 0)
            parts.append(f"--- Done ({dur / 1000:.1f}s) ---")

        budget -= sum(len(p) for p in parts[-3:])

    return "\n".join(parts).strip()


def _extract_tool(tc: dict) -> tuple[str, dict]:
    """Find the tool-specific sub-dict in a tool_call envelope."""
    for key in ("shellToolCall", "readToolCall", "writeToolCall", "editToolCall",
                "grepToolCall", "globToolCall", "listToolCall", "deleteToolCall"):
        if key in tc:
            return key, tc[key]
    for key, val in tc.items():
        if isinstance(val, dict):
            return key, val
    return "unknown", {}


def _describe_tool_start(tc: dict) -> str:
    name, data = _extract_tool(tc)
    args = data.get("args", {})
    if name == "shellToolCall":
        return f"Shell: {(args.get('command') or '?')[:120]}"
    if name == "readToolCall":
        return f"Read {args.get('path', '?')}"
    if name in ("writeToolCall", "editToolCall"):
        label = "Write" if name == "writeToolCall" else "Edit"
        return f"{label} {args.get('path', '?')}"
    if name == "grepToolCall":
        return f"Grep: {args.get('pattern', '?')}"
    if name == "globToolCall":
        return f"Glob: {args.get('pattern') or args.get('glob', '?')}"
    return data.get("description", "")


def _describe_tool_done(tc: dict) -> tuple[str, str]:
    """Return (description, output) for a completed tool call."""
    name, data = _extract_tool(tc)
    result = data.get("result", {})
    success = result.get("success", {})

    if name == "shellToolCall":
        exit_code = success.get("exitCode", success.get("exit_code"))
        stdout = (success.get("stdout") or success.get("output") or "").strip()
        header = f"Shell exit={exit_code}" if exit_code is not None else "Shell completed"
        return header, stdout
    if name == "editToolCall" and success:
        return f"Edited {data.get('args', {}).get('path', '?')}", ""
    if name == "writeToolCall" and success:
        return f"Wrote {success.get('path', '?')}", ""
    return "", ""


class ContextService:
    def __init__(self, project_dir: Path):
        """Initialize with the .llmflows/ directory in a project or worktree."""
        self.project_dir = project_dir

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
            return ""

    def render_summary_step(self, context: dict) -> str:
        """Render summary_step.md as step content for the auto-appended summary step."""
        template_file = DEFAULTS_DIR / "step_summary.md"
        if not template_file.exists():
            return ""
        try:
            env = Environment(autoescape=False)
            template = env.from_string(template_file.read_text())
            return template.render(context)
        except TemplateError:
            return ""

    def render_one_shot(self, context: dict) -> str:
        """Render one_shot.md with all steps assembled into a single prompt."""
        template_file = DEFAULTS_DIR / "one_shot.md"
        if not template_file.exists():
            return ""
        try:
            env = Environment(autoescape=False)
            template = env.from_string(template_file.read_text())
            return template.render(context)
        except TemplateError:
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
                    "result": result_text,
                    "files": files,
                })

        return artifacts

    @staticmethod
    def read_step_log_tail(log_path: str, max_lines: int = LOG_TAIL_LINES) -> str:
        """Read the tail of an agent log file.

        If the log is JSONL (Cursor agent format), extracts only assistant
        messages, tool descriptions, and shell output as readable text.
        Otherwise returns the raw tail capped at LOG_TAIL_MAX_CHARS.
        """
        if not log_path or log_path == "inline":
            return ""
        p = Path(log_path)
        if not p.exists():
            return ""
        try:
            raw = p.read_text(errors="replace")
        except (PermissionError, OSError):
            return ""

        first_line = raw.lstrip()[:1]
        if first_line == "{":
            return _parse_jsonl_log(raw, max_chars=LOG_TAIL_MAX_CHARS)

        lines = raw.splitlines()
        tail = "\n".join(lines[-max_lines:])
        if len(tail) > LOG_TAIL_MAX_CHARS:
            tail = tail[-LOG_TAIL_MAX_CHARS:]
            nl = tail.find("\n")
            if nl != -1:
                tail = tail[nl + 1:]
        return tail.strip()

    @staticmethod
    def read_summary_artifact(artifacts_dir: Path) -> str:
        """Read the summary.md file from the artifacts root, if it exists."""
        summary_file = artifacts_dir / "summary.md"
        if not summary_file.exists():
            return ""
        try:
            return summary_file.read_text().strip()
        except (PermissionError, OSError):
            return ""

    @staticmethod
    def get_artifacts_dir(project_path: Path, task_id: str, run_id: str) -> Path:
        """Return the artifacts directory for a run, always under the main project root."""
        return project_path / ".llmflows" / task_id / run_id / "artifacts"
