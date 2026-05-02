"""Context service -- renders step prompts and collects artifacts."""

import logging
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
