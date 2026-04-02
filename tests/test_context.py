"""Tests for context service."""

from pathlib import Path

from llmflows.services.context import ContextService


class TestContextService:
    def _setup_dirs(self, tmp_path: Path) -> ContextService:
        project_dir = tmp_path / ".llmflows"
        project_dir.mkdir()
        return ContextService(project_dir)

    def test_render_step_instructions(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "task_id": "abc123",
            "task_description": "Build something",
            "user_prompt": "Build something",
            "step_name": "research",
            "step_content": "# Research the problem",
            "flow_name": "default",
            "artifacts": [],
            "artifacts_output_dir": "/tmp/artifacts/00-research",
            "gate_failures": None,
        })
        assert "abc123" in result
        assert "Build something" in result
        assert "Research the problem" in result
        assert "When you have completed" in result

    def test_render_step_instructions_with_artifacts(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "task_id": "abc123",
            "task_description": "Build feature",
            "user_prompt": "Build feature",
            "step_name": "implement",
            "step_content": "# Implement based on research",
            "flow_name": "default",
            "artifacts": [{
                "position": 0,
                "step_name": "research",
                "files": [{"name": "findings.md", "content": "Found the answer."}],
            }],
            "artifacts_output_dir": "/tmp/artifacts/01-implement",
            "gate_failures": None,
        })
        assert "Previous Step Artifacts" in result
        assert "findings.md" in result
        assert "Found the answer." in result

    def test_render_step_instructions_with_gate_failures(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "task_id": "abc123",
            "task_description": "Fix bug",
            "user_prompt": "Fix bug",
            "step_name": "implement",
            "step_content": "# Fix the issue",
            "flow_name": "default",
            "artifacts": [],
            "artifacts_output_dir": "/tmp/artifacts/01-implement",
            "gate_failures": [{
                "command": "pytest tests/",
                "message": "Tests must pass",
                "output": "FAILED test_foo.py",
            }],
        })
        assert "Previous Attempt Failed" in result
        assert "Tests must pass" in result
        assert "FAILED test_foo.py" in result

    def test_render_step_instructions_with_worktree(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "worktree_path": "/tmp/worktrees/task-abc",
            "task_id": "abc123",
            "task_description": "Task desc",
            "user_prompt": "Task desc",
            "step_name": "research",
            "step_content": "Do research",
            "flow_name": "default",
            "artifacts": [],
            "artifacts_output_dir": "/tmp/artifacts/00-research",
            "gate_failures": None,
        })
        assert "/tmp/worktrees/task-abc" in result
        assert "cd /tmp/worktrees/task-abc" in result

    def test_collect_artifacts(self, temp_dir):
        artifacts_dir = temp_dir / "artifacts"
        step_dir = artifacts_dir / "00-research"
        step_dir.mkdir(parents=True)
        (step_dir / "findings.md").write_text("# Findings\nImportant stuff")

        result = ContextService.collect_artifacts(artifacts_dir)
        assert len(result) == 1
        assert result[0]["position"] == 0
        assert result[0]["step_name"] == "research"
        assert result[0]["files"][0]["name"] == "findings.md"
        assert "Important stuff" in result[0]["files"][0]["content"]

    def test_collect_artifacts_empty(self, temp_dir):
        result = ContextService.collect_artifacts(temp_dir / "nonexistent")
        assert result == []

    def test_read_summary_artifact(self, temp_dir):
        artifacts_dir = temp_dir / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "summary.md").write_text("# Summary\nDone.")

        result = ContextService.read_summary_artifact(artifacts_dir)
        assert "Done." in result

    def test_read_summary_artifact_missing(self, temp_dir):
        result = ContextService.read_summary_artifact(temp_dir)
        assert result == ""

    def test_get_artifacts_dir(self, temp_dir):
        result = ContextService.get_artifacts_dir(temp_dir, "task1", "run1")
        assert result == temp_dir / ".llmflows" / "task1" / "run1" / "artifacts"
