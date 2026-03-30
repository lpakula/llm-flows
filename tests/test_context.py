"""Tests for context service."""

from pathlib import Path

from llmflows.services.context import ContextService


class TestContextService:
    def _setup_dirs(self, tmp_path: Path) -> ContextService:
        project_dir = tmp_path / ".llmflows"
        project_dir.mkdir()
        return ContextService(project_dir)

    def test_get_current_flow_default(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        assert svc.get_current_flow() == "default"

    def test_get_current_flow_from_file(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        (svc.project_dir / "flow").write_text("custom")
        assert svc.get_current_flow() == "custom"

    def test_get_current_task_id(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        assert svc.get_current_task_id() == ""
        (svc.project_dir / "task_id").write_text("abc123")
        assert svc.get_current_task_id() == "abc123"

    def test_render_start_instructions(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_start_instructions({
            "flow_name": "default",
            "task_id": "abc123",
            "task_name": "My Task",
            "task_description": "Build something",
            "task_type": "feature",
            "execution_history": [],
        })
        assert "default" in result
        assert "abc123" in result
        assert "llmflows mode next" in result

    def test_render_start_instructions_not_overridable(self, temp_dir):
        """Project-level start.md should not override the package default."""
        svc = self._setup_dirs(temp_dir)
        mode_dir = svc.project_dir / "context" / "mode"
        mode_dir.mkdir(parents=True, exist_ok=True)
        (mode_dir / "start.md").write_text("# Custom Protocol")

        result = svc.render_start_instructions({
            "flow_name": "default",
            "task_id": "t1",
            "task_name": "Test",
            "task_description": "",
            "task_type": "feature",
            "execution_history": [],
        })
        assert "Custom Protocol" not in result
        assert "llmflows Protocol" in result

    def test_load_complete_step(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        content = svc.load_complete_step()
        assert "COMPLETE" in content
        assert "llmflows run complete" in content

    def test_render_start_with_execution_history(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_start_instructions({
            "flow_name": "default",
            "task_id": "abc123",
            "task_name": "Re-run",
            "task_description": "Retry this",
            "task_type": "feature",
            "worktree_path": "/tmp/worktrees/task-abc123",
            "execution_history": [
                {"flow_name": "default", "outcome": "failed", "summary": "It broke"},
            ],
        })
        assert "PREVIOUS RUNS" in result
        assert "It broke" in result
        assert "git diff main...HEAD" in result

    def test_render_recovery_instructions(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_recovery_instructions({
            "flow_name": "default",
            "task_id": "abc123",
            "task_description": "Build the feature",
            "current_step": "execute",
            "steps_completed": ["research"],
            "git_diff": "+ added line",
            "recovery_attempt": 1,
            "execution_history": [],
        })
        assert "Recovery" in result
        assert "abc123" in result
        assert "Build the feature" in result
        assert "execute" in result
        assert "research" in result
        assert "+ added line" in result
        assert "recovery attempt 1" in result

    def test_render_recovery_instructions_no_current_step(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_recovery_instructions({
            "flow_name": "default",
            "task_id": "t001",
            "task_description": "Do the thing",
            "current_step": "",
            "steps_completed": [],
            "git_diff": "",
            "recovery_attempt": 2,
            "execution_history": [],
        })
        assert "Run `llmflows mode next` to start the flow" in result
        assert "re-read the step" not in result

    def test_render_recovery_instructions_at_complete_step(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_recovery_instructions({
            "flow_name": "default",
            "task_id": "t002",
            "task_description": "Finish up",
            "current_step": "complete",
            "steps_completed": ["research", "execute"],
            "git_diff": "some diff",
            "recovery_attempt": 1,
            "execution_history": [],
        })
        assert "completion step" in result
        assert "llmflows mode current" in result
