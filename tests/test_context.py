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

    def test_read_improvement(self, temp_dir):
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "improvement.md").write_text("## Better error handling\n\nAdded retry logic.")
        result = ContextService.read_improvement(temp_dir)
        assert "Better error handling" in result

    def test_read_improvement_missing(self, temp_dir):
        result = ContextService.read_improvement(temp_dir)
        assert result == ""

    def test_read_flow_json(self, temp_dir):
        import json
        flow = {
            "description": "improved flow",
            "steps": [{"name": "step1", "position": 0, "content": "# Step 1"}],
        }
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "flow.json").write_text(json.dumps(flow))
        result = ContextService.read_flow_json(temp_dir)
        assert result is not None
        assert len(result["steps"]) == 1

    def test_read_flow_json_missing(self, temp_dir):
        result = ContextService.read_flow_json(temp_dir)
        assert result is None

    def test_read_flow_json_invalid(self, temp_dir):
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "flow.json").write_text("not json")
        result = ContextService.read_flow_json(temp_dir)
        assert result is None

    def test_read_flow_json_no_steps(self, temp_dir):
        import json
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "flow.json").write_text(json.dumps({"description": "no steps"}))
        result = ContextService.read_flow_json(temp_dir)
        assert result is None

    def test_list_memory_files(self, temp_dir):
        flow_dir = temp_dir / "flow"
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "notes.md").write_text("Some notes here.")
        (mem_dir / "rejected-proposals.md").write_text("## Rejected\nDon't add steps.")
        result = ContextService.list_memory_files(flow_dir)
        assert len(result) == 2
        names = [f["name"] for f in result]
        assert "notes.md" in names
        assert "rejected-proposals.md" in names

    def test_list_memory_files_empty(self, temp_dir):
        result = ContextService.list_memory_files(temp_dir)
        assert result == []

    def test_list_memory_files_skips_empty(self, temp_dir):
        flow_dir = temp_dir / "flow"
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "empty.md").write_text("")
        (mem_dir / "has-content.md").write_text("content")
        result = ContextService.list_memory_files(flow_dir)
        assert len(result) == 1
        assert result[0]["name"] == "has-content.md"

    def test_read_all_memory(self, temp_dir):
        flow_dir = temp_dir / "flow"
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "a.md").write_text("First file.")
        (mem_dir / "b.md").write_text("Second file.")
        result = ContextService.read_all_memory(flow_dir)
        assert "a.md" in result
        assert "First file." in result
        assert "b.md" in result
        assert "Second file." in result

    def test_read_memory_backward_compat(self, temp_dir):
        flow_dir = temp_dir / "flow"
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "data.md").write_text("Some data.")
        result = ContextService.read_memory(flow_dir)
        assert "Some data." in result

    def test_write_memory_file(self, temp_dir):
        flow_dir = temp_dir / "flow"
        ContextService.write_memory_file(flow_dir, "notes.md", "# Notes\nImportant.")
        mem_file = flow_dir / "memory" / "notes.md"
        assert mem_file.exists()
        assert "Important" in mem_file.read_text()

    def test_write_memory_file_overwrite(self, temp_dir):
        flow_dir = temp_dir / "flow"
        ContextService.write_memory_file(flow_dir, "notes.md", "v1")
        ContextService.write_memory_file(flow_dir, "notes.md", "v2")
        content = (flow_dir / "memory" / "notes.md").read_text()
        assert content == "v2"

    def test_delete_memory_file(self, temp_dir):
        flow_dir = temp_dir / "flow"
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "notes.md").write_text("content")
        assert ContextService.delete_memory_file(flow_dir, "notes.md") is True
        assert not (mem_dir / "notes.md").exists()

    def test_delete_memory_file_missing(self, temp_dir):
        assert ContextService.delete_memory_file(temp_dir, "nope.md") is False

    def test_append_memory_new_file(self, temp_dir):
        flow_dir = temp_dir / "flow"
        flow_dir.mkdir(parents=True)
        ContextService.append_memory(flow_dir, "## First entry\nSome content.")
        memory_file = flow_dir / "memory" / "rejected-proposals.md"
        assert memory_file.exists()
        content = memory_file.read_text()
        assert "First entry" in content
        assert "Some content" in content

    def test_append_memory_existing_file(self, temp_dir):
        flow_dir = temp_dir / "flow"
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "rejected-proposals.md").write_text("## First\nOld entry.")
        ContextService.append_memory(flow_dir, "## Second\nNew entry.")
        content = (mem_dir / "rejected-proposals.md").read_text()
        assert "First" in content
        assert "Old entry" in content
        assert "---" in content
        assert "Second" in content
        assert "New entry" in content

    def test_append_memory_creates_directory(self, temp_dir):
        flow_dir = temp_dir / "nonexistent" / "flow"
        ContextService.append_memory(flow_dir, "## Entry\nContent.")
        assert (flow_dir / "memory" / "rejected-proposals.md").exists()

    def test_migrate_legacy_memory(self, temp_dir):
        flow_dir = temp_dir / "flow"
        flow_dir.mkdir(parents=True)
        (flow_dir / "memory.md").write_text("## Old rejected\nLegacy content.")
        files = ContextService.list_memory_files(flow_dir)
        assert len(files) == 1
        assert files[0]["name"] == "rejected-proposals.md"
        assert "Legacy content" in files[0]["content"]
        assert not (flow_dir / "memory.md").exists()

    def test_migrate_legacy_memory_empty(self, temp_dir):
        flow_dir = temp_dir / "flow"
        flow_dir.mkdir(parents=True)
        (flow_dir / "memory.md").write_text("   ")
        files = ContextService.list_memory_files(flow_dir)
        assert files == []
        assert not (flow_dir / "memory.md").exists()

    def test_read_rejected_proposals(self, temp_dir):
        flow_dir = temp_dir / "flow"
        mem_dir = flow_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "rejected-proposals.md").write_text("Don't add steps.")
        (mem_dir / "context.md").write_text("Extra context.")
        result = ContextService.read_rejected_proposals(flow_dir)
        assert len(result) == 1
        assert result[0]["name"] == "rejected-proposals.md"
        assert "Don't add steps" in result[0]["content"]

    def test_read_rejected_proposals_empty(self, temp_dir):
        result = ContextService.read_rejected_proposals(temp_dir)
        assert result == []

    def test_read_rejected_proposals_migrates_legacy(self, temp_dir):
        flow_dir = temp_dir / "flow"
        flow_dir.mkdir(parents=True)
        (flow_dir / "memory.md").write_text("Legacy rejected content.")
        result = ContextService.read_rejected_proposals(flow_dir)
        assert len(result) == 1
        assert "Legacy rejected content" in result[0]["content"]
        assert not (flow_dir / "memory.md").exists()

    def test_get_memory_dir(self, temp_dir):
        flow_dir = temp_dir / "flow"
        result = ContextService.get_memory_dir(flow_dir)
        assert result == flow_dir / "memory"

    def test_render_post_run_step(self, temp_dir):
        ctx = ContextService(temp_dir)
        result = ctx.render_post_run_step({
            "run": {"id": "abc123", "dir": "/tmp/run"},
            "flow_name": "test-flow",
            "outcome": "completed",
            "language": "English",
        })
        assert "POST-RUN ANALYSIS" in result
        assert "test-flow" in result

    def test_render_post_run_step_with_error(self, temp_dir):
        ctx = ContextService(temp_dir)
        result = ctx.render_post_run_step({
            "run": {"id": "abc123", "dir": "/tmp/run"},
            "flow_name": "test-flow",
            "outcome": "error",
            "language": "English",
            "error_details": "Step crashed with OOM",
            "failed_step": "build",
            "log_tail": "Out of memory",
        })
        assert "Error Details" in result
        assert "OOM" in result
        assert "build" in result

    def test_post_run_template_includes_rejected_proposals(self, temp_dir):
        """Verify the post-run template renders rejected proposals when provided."""
        from jinja2 import Environment, ChainableUndefined
        from llmflows.services.context import DEFAULTS_DIR
        template_file = DEFAULTS_DIR / "step_post_run.md"
        if not template_file.exists():
            return
        env = Environment(autoescape=False, undefined=ChainableUndefined)
        template = env.from_string(template_file.read_text())
        result = template.render({
            "run": {"id": "abc123", "dir": "/tmp/run"},
            "flow_name": "test-flow",
            "flow_version": 2,
            "outcome": "completed",
            "language": "English",
            "memory_files": [
                {"name": "rejected-proposals.md", "content": "Don't split the research step."},
            ],
        })
        assert "Rejected Proposals" in result
        assert "Don't split the research step" in result

    def test_post_run_template_excludes_memory_when_empty(self, temp_dir):
        """Verify the post-run template omits rejected proposals section when not provided."""
        from jinja2 import Environment, ChainableUndefined
        from llmflows.services.context import DEFAULTS_DIR
        template_file = DEFAULTS_DIR / "step_post_run.md"
        if not template_file.exists():
            return
        env = Environment(autoescape=False, undefined=ChainableUndefined)
        template = env.from_string(template_file.read_text())
        result = template.render({
            "run": {"id": "abc123", "dir": "/tmp/run"},
            "flow_name": "test-flow",
            "flow_version": 1,
            "outcome": "completed",
            "language": "English",
        })
        assert "Rejected Proposals" not in result

    def test_step_template_does_not_include_memory(self, temp_dir):
        """Step prompts do not inject memory files — steps manage their own."""
        svc = self._setup_dirs(temp_dir)
        result = svc.render_step_instructions({
            "run_id": "abc123",
            "run": {"id": "abc123", "dir": "/tmp/artifacts"},
            "step_name": "implement",
            "step": {"dir": "/tmp/artifacts/01-implement"},
            "step_content": "# Do the work",
            "flow_name": "default",
            "flow": {"name": "default", "dir": "/tmp/flow"},
            "artifacts": [],
            "artifacts_dir": "/tmp/artifacts/01-implement",
            "attachment": {"dir": "/tmp/attachments"},
            "gate_failures": None,
        })
        assert "Flow Memory" not in result
