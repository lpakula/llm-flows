"""Context service -- renders step prompts and collects artifacts."""

import os
from pathlib import Path

from jinja2 import Environment, TemplateError

from ..defaults import get_defaults_dir

DEFAULTS_DIR = get_defaults_dir()


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

    @staticmethod
    def collect_artifacts(artifacts_dir: Path) -> list[dict]:
        """Collect artifacts from completed steps.

        Returns a list of dicts, each with:
          - position: int
          - step_name: str
          - files: list of {name, content}
        """
        if not artifacts_dir.exists():
            return []

        artifacts = []
        try:
            step_dirs = sorted(
                d for d in artifacts_dir.iterdir()
                if d.is_dir() and d.name[0:2].isdigit()
            )
        except (PermissionError, OSError):
            return []

        for step_dir in step_dirs:
            parts = step_dir.name.split("-", 1)
            try:
                position = int(parts[0])
            except (ValueError, IndexError):
                continue
            step_name = parts[1] if len(parts) > 1 else step_dir.name

            files = []
            try:
                for f in sorted(step_dir.iterdir()):
                    if not f.is_file():
                        continue
                    try:
                        content = f.read_text(errors="replace")
                        if len(content) > 10000:
                            content = content[:10000] + "\n... (truncated)"
                        files.append({"name": f.name, "content": content})
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError):
                continue

            if files:
                artifacts.append({
                    "position": position,
                    "step_name": step_name,
                    "files": files,
                })

        return artifacts

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
