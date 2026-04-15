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
            "run_id": "abc123",
            "step_name": "research",
            "step_content": "# Research the problem",
            "flow_name": "default",
            "artifacts": [],
            "artifacts_dir": "/tmp/artifacts/00-research",
            "gate_failures": None,
        })
        assert "abc123" in result
        assert "Research the problem" in result
        assert "When you have completed" in result

    def test_render_step_instructions_with_artifacts(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "run_id": "abc123",
            "step_name": "implement",
            "step_content": "# Implement based on research",
            "flow_name": "default",
            "artifacts": [{
                "position": 0,
                "step_name": "research",
                "result": None,
                "files": [{"name": "findings.md", "content": "Found the answer."}],
            }],
            "artifacts_dir": "/tmp/artifacts/01-implement",
            "gate_failures": None,
        })
        assert "Previous Step Artifacts" in result
        assert "findings.md" in result
        assert "Found the answer." in result

    def test_render_step_instructions_with_gate_failures(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "run_id": "abc123",
            "step_name": "implement",
            "step_content": "# Fix the issue",
            "flow_name": "default",
            "artifacts": [],
            "artifacts_dir": "/tmp/artifacts/01-implement",
            "gate_failures": [{
                "command": "pytest tests/",
                "message": "Tests must pass",
                "output": "FAILED test_foo.py",
            }],
        })
        assert "Previous Attempt Failed" in result
        assert "Tests must pass" in result
        assert "FAILED test_foo.py" in result

    def test_collect_artifacts(self, temp_dir):
        artifacts_dir = temp_dir / "artifacts"
        step_dir = artifacts_dir / "00-research"
        step_dir.mkdir(parents=True)
        (step_dir / "findings.md").write_text("# Findings\nImportant stuff")

        result = ContextService.collect_artifacts(artifacts_dir)
        assert len(result) == 1
        assert result[0]["position"] == 0
        assert result[0]["step_name"] == "research"
        assert result[0]["result"] is None
        assert result[0]["files"][0]["name"] == "findings.md"
        assert "Important stuff" in result[0]["files"][0]["content"]

    def test_collect_artifacts_with_result(self, temp_dir):
        artifacts_dir = temp_dir / "artifacts"
        step_dir = artifacts_dir / "00-research"
        step_dir.mkdir(parents=True)
        (step_dir / "_result.md").write_text("## What was done\nResearched the problem.")
        (step_dir / "data.json").write_text('{"key": "value"}')

        result = ContextService.collect_artifacts(artifacts_dir)
        assert len(result) == 1
        assert result[0]["result"] is not None
        assert "Researched the problem" in result[0]["result"]
        assert len(result[0]["files"]) == 1
        assert result[0]["files"][0]["name"] == "data.json"

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
        result = ContextService.get_artifacts_dir(temp_dir, "run1")
        assert result == temp_dir / ".llmflows" / "runs" / "run1" / "artifacts"
