"""Context service -- renders start instructions and loads worktree diff.

Step content is loaded from the database via FlowService.
System templates (start.md, complete.md) live in package defaults.
"""

from pathlib import Path

from jinja2 import Environment, TemplateError

from ..defaults import get_defaults_dir

DEFAULTS_DIR = get_defaults_dir()


class ContextService:
    def __init__(self, project_dir: Path):
        """Initialize with the .llmflows/ directory in a project or worktree."""
        self.project_dir = project_dir

    @classmethod
    def find(cls, repo_root: Path) -> "ContextService":
        """Return the right ContextService for the current execution mode.

        In worktree mode, task_id/run_id live directly in <repo>/.llmflows/.
        In no-worktree mode they live in <repo>/.llmflows/<task_id>/ so that
        multiple concurrent tasks don't collide. Fall back to the
        most-recently-touched subdirectory that contains a run_id file.
        """
        base = repo_root / ".llmflows"
        ctx = cls(base)
        if ctx.get_current_task_id() or ctx.get_current_run_id():
            return ctx
        try:
            subdirs = sorted(
                [d for d in base.iterdir() if d.is_dir() and (d / "run_id").exists()],
                key=lambda d: (d / "run_id").stat().st_mtime,
                reverse=True,
            )
        except (FileNotFoundError, PermissionError):
            subdirs = []
        return cls(subdirs[0]) if subdirs else ctx

    def get_current_flow(self) -> str:
        """Read the current flow from .llmflows/flow. Defaults to 'default'."""
        flow_file = self.project_dir / "flow"
        if flow_file.exists():
            try:
                return flow_file.read_text().strip() or "default"
            except Exception:
                pass
        return "default"


    def get_current_task_id(self) -> str:
        """Read the current task_id from .llmflows/task_id."""
        task_id_file = self.project_dir / "task_id"
        if task_id_file.exists():
            try:
                return task_id_file.read_text().strip()
            except Exception:
                pass
        return ""

    def get_current_run_id(self) -> str:
        """Read the current run_id from .llmflows/run_id."""
        run_id_file = self.project_dir / "run_id"
        if run_id_file.exists():
            try:
                return run_id_file.read_text().strip()
            except Exception:
                pass
        return ""

    def render_start_instructions(self, context: dict) -> str:
        """Render start.md as the full agent prompt."""
        start_file = DEFAULTS_DIR / "start.md"
        if not start_file.exists():
            return ""
        try:
            env = Environment(autoescape=False)
            template = env.from_string(start_file.read_text())
            return template.render(context)
        except TemplateError:
            return ""

    def load_complete_step(self) -> str:
        """Load the auto-appended complete step content."""
        complete_file = DEFAULTS_DIR / "complete.md"
        if not complete_file.exists():
            return ""
        try:
            return complete_file.read_text()
        except Exception:
            return ""

    def load_worktree_diff(self) -> str:
        """Load the git diff from the worktree against the base branch."""
        from ..utils.git import get_worktree_diff
        worktree_root = self.project_dir.parent
        return get_worktree_diff(base="main", cwd=str(worktree_root))
