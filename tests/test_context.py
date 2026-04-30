"""Tests for context service."""

from pathlib import Path

from llmflows.services.context import ContextService


class TestContextService:
    def _setup_dirs(self, tmp_path: Path) -> ContextService:
        space_dir = tmp_path / ".llmflows"
        space_dir.mkdir()
        return ContextService(space_dir)

    def test_render_step_instructions(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "run_id": "abc123",
            "run": {"id": "abc123", "dir": "/tmp/artifacts"},
            "step_name": "research",
            "step": {"dir": "/tmp/artifacts/00-research"},
            "step_content": "# Research the problem",
            "flow_name": "default",
            "flow": {"name": "default", "dir": ""},
            "artifacts": [],
            "artifacts_dir": "/tmp/artifacts/00-research",
            "attachment": {"dir": "/tmp/attachments"},
            "gate_failures": None,
        })
        assert "abc123" in result
        assert "Research the problem" in result
        assert "When you have completed" in result

    def test_render_step_instructions_with_artifacts(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "run_id": "abc123",
            "run": {"id": "abc123", "dir": "/tmp/artifacts"},
            "step_name": "implement",
            "step": {"dir": "/tmp/artifacts/01-implement"},
            "step_content": "# Implement based on research",
            "flow_name": "default",
            "flow": {"name": "default", "dir": ""},
            "artifacts": [{
                "position": 0,
                "step_name": "research",
                "path": "/tmp/artifacts/00-research",
                "result": None,
                "files": [{"name": "findings.md", "content": "Found the answer."}],
            }],
            "artifacts_dir": "/tmp/artifacts/01-implement",
            "attachment": {"dir": "/tmp/attachments"},
            "gate_failures": None,
        })
        assert "Previous Step Artifacts" in result
        assert "findings.md" in result
        assert "Found the answer." in result

    def test_render_step_instructions_with_gate_failures(self, temp_dir):
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "run_id": "abc123",
            "run": {"id": "abc123", "dir": "/tmp/artifacts"},
            "step_name": "implement",
            "step": {"dir": "/tmp/artifacts/01-implement"},
            "step_content": "# Fix the issue",
            "flow_name": "default",
            "flow": {"name": "default", "dir": ""},
            "artifacts": [],
            "artifacts_dir": "/tmp/artifacts/01-implement",
            "attachment": {"dir": "/tmp/attachments"},
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
        result = ContextService.get_artifacts_dir(temp_dir, "run1", "my-flow")
        assert result == temp_dir / ".llmflows" / "my-flow" / "runs" / "run1" / "artifacts"

    def test_get_artifacts_dir_default(self, temp_dir):
        result = ContextService.get_artifacts_dir(temp_dir, "run1")
        assert result == temp_dir / ".llmflows" / "_default" / "runs" / "run1" / "artifacts"

    def test_get_flow_dir(self, temp_dir):
        result = ContextService.get_flow_dir(temp_dir, "my-flow")
        assert result == temp_dir / ".llmflows" / "my-flow"

    def test_get_flow_dir_default(self, temp_dir):
        result = ContextService.get_flow_dir(temp_dir)
        assert result == temp_dir / ".llmflows" / "_default"

    def test_safe_flow_dir(self):
        assert ContextService._safe_flow_dir("My Flow") == "my-flow"
        assert ContextService._safe_flow_dir("crypto-news") == "crypto-news"
        assert ContextService._safe_flow_dir("") == "_default"
        assert ContextService._safe_flow_dir("  ") == "_default"

    def test_read_flow_proposal(self, temp_dir):
        import json
        proposal = {
            "description": "improved flow",
            "improvement_summary": "Added better error handling",
            "steps": [{"name": "step1", "position": 0, "content": "# Step 1"}],
        }
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "flow_proposal.json").write_text(json.dumps(proposal))
        result = ContextService.read_flow_proposal(temp_dir)
        assert result is not None
        assert result["improvement_summary"] == "Added better error handling"
        assert len(result["steps"]) == 1

    def test_read_flow_proposal_missing(self, temp_dir):
        result = ContextService.read_flow_proposal(temp_dir)
        assert result is None

    def test_read_flow_proposal_invalid_json(self, temp_dir):
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "flow_proposal.json").write_text("not json")
        result = ContextService.read_flow_proposal(temp_dir)
        assert result is None

    def test_read_flow_proposal_no_steps(self, temp_dir):
        import json
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "flow_proposal.json").write_text(json.dumps({"description": "no steps"}))
        result = ContextService.read_flow_proposal(temp_dir)
        assert result is None

    def test_render_post_run_step(self, temp_dir):
        ctx = ContextService(temp_dir)
        result = ctx.render_post_run_step({
            "run": {"id": "abc123", "dir": "/tmp/run"},
            "flow_name": "test-flow",
            "outcome": "completed",
            "summarizer_language": "English",
        })
        assert "POST-RUN ANALYSIS" in result
        assert "test-flow" in result

    def test_render_post_run_step_with_error(self, temp_dir):
        ctx = ContextService(temp_dir)
        result = ctx.render_post_run_step({
            "run": {"id": "abc123", "dir": "/tmp/run"},
            "flow_name": "test-flow",
            "outcome": "error",
            "summarizer_language": "English",
            "error_details": "Step crashed with OOM",
            "failed_step": "build",
            "log_tail": "Out of memory",
        })
        assert "Error Details" in result
        assert "OOM" in result
        assert "build" in result
