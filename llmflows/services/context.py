"""Context service -- renders step prompts and collects artifacts."""


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
