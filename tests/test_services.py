"""Tests for service layer."""

import json
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from llmflows.db.models import FlowStep
from llmflows.services.agent import AgentService
from llmflows.services.flow import FlowService
from llmflows.services.gate import evaluate_gates
from llmflows.services.space import SpaceService
from llmflows.services.run import RunService


class TestSpaceService:
    def test_register(self, test_db):
        svc = SpaceService(test_db)
        space = svc.register("test", "/tmp/test")
        assert space.name == "test"
        # Paths are normalized on registration (e.g. /tmp → /private/tmp on macOS).
        assert space.path == str(Path("/tmp/test").resolve())

    def test_register_idempotent(self, test_db):
        svc = SpaceService(test_db)
        s1 = svc.register("test", "/tmp/test")
        s2 = svc.register("test", "/tmp/test")
        assert s1.id == s2.id

    def test_unregister(self, test_db):
        svc = SpaceService(test_db)
        space = svc.register("test", "/tmp/test")
        assert svc.unregister(space.id) is True
        assert svc.get(space.id) is None

    def test_unregister_nonexistent(self, test_db):
        svc = SpaceService(test_db)
        assert svc.unregister("nope") is False

    def test_list_all(self, test_db):
        svc = SpaceService(test_db)
        svc.register("a", "/tmp/a")
        svc.register("b", "/tmp/b")
        assert len(svc.list_all()) == 2

    def test_get_by_path(self, test_db):
        svc = SpaceService(test_db)
        svc.register("test", "/tmp/test")
        found = svc.get_by_path("/tmp/test")
        assert found is not None
        assert found.name == "test"

    def test_get_by_path_not_found(self, test_db):
        svc = SpaceService(test_db)
        assert svc.get_by_path("/tmp/nope") is None

    def test_resolve_current_uses_space_host_path_in_runner(self, test_db, monkeypatch):
        svc = SpaceService(test_db)
        space = svc.register("personal", "/Users/me/proj")
        monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
        monkeypatch.chdir("/")
        assert svc.resolve_current().id == space.id

    def test_register_maps_container_workspace_to_host(self, test_db, monkeypatch):
        svc = SpaceService(test_db)
        monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
        space = svc.register("workspace", "/workspace")
        assert space.path == "/Users/me/proj"
        assert len(svc.list_all()) == 1

    def test_register_rejects_bare_workspace_without_host(self, test_db, monkeypatch):
        svc = SpaceService(test_db)
        monkeypatch.delenv("LLMFLOWS_SPACE_HOST_PATH", raising=False)
        with pytest.raises(ValueError, match="/workspace"):
            svc.register("workspace", "/workspace")


class TestFlowService:
    def test_create_flow(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("test-flow", space_id=test_space.id, description="A test flow")
        assert flow.name == "test-flow"
        assert flow.description == "A test flow"

    def test_create_flow_with_steps(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("with-steps", space_id=test_space.id, steps=[
            {"name": "research", "position": 0, "content": "# Research"},
            {"name": "execute", "position": 1, "content": "# Execute"},
        ])
        assert len(flow.steps) == 2
        assert flow.steps[0].name == "research"

    def test_create_flow_duplicate_name(self, test_db, test_space):
        import pytest
        svc = FlowService(test_db)
        svc.create("dup-test", space_id=test_space.id)
        with pytest.raises(ValueError, match="already exists"):
            svc.create("dup-test", space_id=test_space.id)

    def test_get_by_name(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("lookup", space_id=test_space.id)
        found = svc.get_by_name("lookup", test_space.id)
        assert found is not None
        assert found.name == "lookup"

    def test_list_by_space(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("flow-a", space_id=test_space.id)
        svc.create("flow-b", space_id=test_space.id)
        flows = svc.list_by_space(test_space.id)
        assert len(flows) == 2

    def test_update(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("update-test", space_id=test_space.id, description="Old")
        svc.update(flow.id, description="New")
        updated = svc.get(flow.id)
        assert updated.description == "New"

    def test_delete(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("delete-me", space_id=test_space.id)
        assert svc.delete(flow.id) is True
        assert svc.get(flow.id) is None

    def test_delete_with_runs(self, test_db, test_space):
        from llmflows.db.models import FlowRun

        svc = FlowService(test_db)
        flow = svc.create("delete-with-runs", space_id=test_space.id)
        run = FlowRun(space_id=test_space.id, flow_id=flow.id, flow_snapshot='{"name":"delete-with-runs"}')
        test_db.add(run)
        test_db.commit()

        assert svc.delete(flow.id) is True
        assert svc.get(flow.id) is None
        kept = test_db.query(FlowRun).filter_by(id=run.id).first()
        assert kept is not None
        assert kept.flow_id is None

    def test_add_step(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("step-test", space_id=test_space.id)
        step = svc.add_step(flow.id, "research", "# Research content")
        assert step.name == "research"
        assert step.content == "# Research content"

    def test_update_step(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("step-update", space_id=test_space.id)
        step = svc.add_step(flow.id, "test", "old content")
        svc.update_step(step.id, content="new content")
        updated = test_db.query(FlowStep).filter_by(id=step.id).first()
        assert updated.content == "new content"

    def test_remove_step(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("step-remove", space_id=test_space.id)
        step = svc.add_step(flow.id, "test", "content")
        assert svc.remove_step(step.id) is True
        assert test_db.query(FlowStep).filter_by(id=step.id).first() is None

    def test_reorder_steps(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("reorder", space_id=test_space.id)
        s1 = svc.add_step(flow.id, "a", "", 0)
        s2 = svc.add_step(flow.id, "b", "", 1)
        s3 = svc.add_step(flow.id, "c", "", 2)
        svc.reorder_steps(flow.id, [s3.id, s1.id, s2.id])
        flow = svc.get(flow.id)
        names = [s.name for s in sorted(flow.steps, key=lambda s: s.position)]
        assert names == ["c", "a", "b"]

    def test_get_step_obj(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("content-test", space_id=test_space.id, steps=[
            {"name": "research", "content": "# Do Research"},
        ])
        step = svc.get_step_obj("content-test", "research", space_id=test_space.id)
        assert step is not None
        assert step.content == "# Do Research"

    def test_get_step_obj_not_found(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("no-step", space_id=test_space.id)
        assert svc.get_step_obj("no-step", "nonexistent", space_id=test_space.id) is None

    def test_get_flow_steps(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("ordered", space_id=test_space.id, steps=[
            {"name": "b", "position": 1},
            {"name": "a", "position": 0},
            {"name": "c", "position": 2},
        ])
        steps = svc.get_flow_steps("ordered", space_id=test_space.id)
        assert steps == ["a", "b", "c"]

    def test_get_next_step(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("next-test", space_id=test_space.id, steps=[
            {"name": "research", "position": 0},
            {"name": "execute", "position": 1},
            {"name": "summary", "position": 2},
        ])
        assert svc.get_next_step("next-test", "research", space_id=test_space.id) == "execute"
        assert svc.get_next_step("next-test", "execute", space_id=test_space.id) == "summary"
        assert svc.get_next_step("next-test", "summary", space_id=test_space.id) is None

    def test_duplicate(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("source", space_id=test_space.id, description="Original", steps=[
            {"name": "step1", "position": 0, "content": "Content 1"},
        ])
        copy = svc.duplicate("source", "copy", space_id=test_space.id)
        assert copy.name == "copy"
        assert copy.description == "Original"
        assert len(copy.steps) == 1
        assert copy.steps[0].content == "Content 1"

    def test_export_import_round_trip(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("export-test", space_id=test_space.id, description="For export", steps=[
            {"name": "step1", "position": 0, "content": "# Step 1"},
            {"name": "step2", "position": 1, "content": "# Step 2"},
        ])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        svc.export_flows(test_space.id, path)

        data = json.loads(path.read_text())
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "export-test"
        assert len(data["flows"][0]["steps"]) == 2

        for step in list(svc.get_by_name("export-test", test_space.id).steps):
            test_db.delete(step)
        test_db.delete(svc.get_by_name("export-test", test_space.id))
        test_db.commit()

        count = svc.import_flows(path, test_space.id)
        assert count == 1
        reimported = svc.get_by_name("export-test", test_space.id)
        assert reimported is not None
        assert len(reimported.steps) == 2

        path.unlink()

    def test_create_flow_with_gates(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("gated-flow", space_id=test_space.id, steps=[
            {
                "name": "execute",
                "position": 0,
                "content": "# Execute",
                "gates": [
                    {"command": "test -f output.txt", "message": "Output file exists"},
                ],
            },
            {"name": "commit", "position": 1, "content": "# Commit"},
        ])
        assert len(flow.steps) == 2
        assert flow.steps[0].get_gates() == [
            {"command": "test -f output.txt", "message": "Output file exists"},
        ]
        assert flow.steps[1].get_gates() == []

    def test_add_step_with_gates(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("add-gated", space_id=test_space.id)
        step = svc.add_step(
            flow.id, "test", "# Test",
            gates=[{"command": "npm test", "message": "Tests pass"}],
        )
        assert step.get_gates() == [{"command": "npm test", "message": "Tests pass"}]

    def test_step_obj_has_gates(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("gate-content", space_id=test_space.id, steps=[
            {
                "name": "build",
                "position": 0,
                "content": "# Build",
                "gates": [{"command": "make build", "message": "Build succeeds"}],
            },
        ])
        step = svc.get_step_obj("gate-content", "build", space_id=test_space.id)
        assert step is not None
        assert step.content == "# Build"
        gates = step.get_gates()
        assert len(gates) == 1
        assert gates[0]["command"] == "make build"

    def test_duplicate_preserves_gates(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("src-gates", space_id=test_space.id, steps=[
            {
                "name": "test",
                "position": 0,
                "content": "# Test",
                "gates": [{"command": "pytest", "message": "Tests pass"}],
            },
        ])
        copy = svc.duplicate("src-gates", "dst-gates", space_id=test_space.id)
        assert copy.steps[0].get_gates() == [{"command": "pytest", "message": "Tests pass"}]

    def test_export_import_gates_round_trip(self, test_db, test_space):
        svc = FlowService(test_db)
        gates = [{"command": "ls *.png", "message": "Screenshots exist"}]
        svc.create("gate-export", space_id=test_space.id, steps=[
            {"name": "test", "position": 0, "content": "# Test", "gates": gates},
        ])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        svc.export_flows(test_space.id, path)
        data = json.loads(path.read_text())
        exported_gates = data["flows"][0]["steps"][0].get("gates", [])
        assert exported_gates == gates

        for step in list(svc.get_by_name("gate-export", test_space.id).steps):
            test_db.delete(step)
        test_db.delete(svc.get_by_name("gate-export", test_space.id))
        test_db.commit()

        svc.import_flows(path, test_space.id)
        reimported = svc.get_by_name("gate-export", test_space.id)
        assert reimported.steps[0].get_gates() == gates
        path.unlink()


class TestGateEvaluation:
    def test_passing_gate(self, temp_dir):
        gates = [{"command": "true", "message": "Always passes"}]
        failures = evaluate_gates(gates, temp_dir)
        assert failures == []

    def test_failing_gate(self, temp_dir):
        gates = [{"command": "false", "message": "Always fails"}]
        failures = evaluate_gates(gates, temp_dir)
        assert len(failures) == 1
        assert failures[0]["message"] == "Always fails"
        assert failures[0]["exit_code"] != 0

    def test_multiple_gates_all_pass(self, temp_dir):
        (temp_dir / "hello.txt").write_text("hi")
        gates = [
            {"command": "true", "message": "First"},
            {"command": "test -f hello.txt", "message": "File exists"},
        ]
        failures = evaluate_gates(gates, temp_dir)
        assert failures == []

    def test_multiple_gates_partial_failure(self, temp_dir):
        gates = [
            {"command": "true", "message": "Passes"},
            {"command": "test -f nonexistent.txt", "message": "Missing file"},
        ]
        failures = evaluate_gates(gates, temp_dir)
        assert len(failures) == 1
        assert failures[0]["message"] == "Missing file"

    def test_file_exists_gate(self, temp_dir):
        gates = [{"command": "test -f output.txt", "message": "Output exists"}]
        failures = evaluate_gates(gates, temp_dir)
        assert len(failures) == 1

        (temp_dir / "output.txt").write_text("data")
        failures = evaluate_gates(gates, temp_dir)
        assert failures == []

    def test_glob_gate(self, temp_dir):
        gates = [{"command": "ls *.png 2>/dev/null | grep -q .", "message": "PNG files exist"}]
        failures = evaluate_gates(gates, temp_dir)
        assert len(failures) == 1

        (temp_dir / "screenshot.png").write_text("fake png")
        failures = evaluate_gates(gates, temp_dir)
        assert failures == []

    def test_gate_timeout(self, temp_dir):
        gates = [{"command": "sleep 10", "message": "Slow command"}]
        failures = evaluate_gates(gates, temp_dir, timeout=1)
        assert len(failures) == 1
        assert "Timed out" in failures[0]["stderr"]

    def test_empty_gates(self, temp_dir):
        assert evaluate_gates([], temp_dir) == []

    def test_gate_stderr_captured(self, temp_dir):
        gates = [{"command": "echo 'bad thing' >&2 && false", "message": "Fails with stderr"}]
        failures = evaluate_gates(gates, temp_dir)
        assert len(failures) == 1
        assert "bad thing" in failures[0]["stderr"]

    def test_gate_without_message_uses_command(self, temp_dir):
        gates = [{"command": "false"}]
        failures = evaluate_gates(gates, temp_dir)
        assert failures[0]["message"] == "false"

    def test_gate_interpolation(self, temp_dir):
        run_dir = temp_dir / "abc123"
        run_dir.mkdir()
        (run_dir / "screenshot.png").write_text("fake")
        gates = [
            {"command": "ls {{run.id}}/*.png | grep -q .", "message": "Screenshots in {{run.id}}/"},
        ]
        variables = {"run.id": "abc123", "flow.name": "react-js"}
        failures = evaluate_gates(gates, temp_dir, variables=variables)
        assert failures == []

    def test_gate_interpolation_missing_var_preserved(self, temp_dir):
        gates = [{"command": "echo {{unknown.var}}", "message": "test"}]
        failures = evaluate_gates(gates, temp_dir, variables={"run.id": "x"})
        assert failures == []

    def test_gate_runs_in_cwd(self, temp_dir):
        subdir = temp_dir / "sub"
        subdir.mkdir()
        (subdir / "marker.txt").write_text("here")
        gates = [{"command": "test -f marker.txt", "message": "Marker exists"}]
        failures = evaluate_gates(gates, subdir)
        assert failures == []
        failures = evaluate_gates(gates, temp_dir)
        assert len(failures) == 1


class TestRenderStepContent:
    """Tests for Jinja2-based step content rendering."""

    def test_simple_variable_substitution(self):
        from llmflows.services.gate import render_step_content
        text = "Issue #{{flow.ISSUE_NUMBER}} — {{flow.ISSUE_TITLE}}"
        variables = {"flow.ISSUE_NUMBER": "27", "flow.ISSUE_TITLE": "Add auth"}
        result = render_step_content(text, variables)
        assert result == "Issue #27 — Add auth"

    def test_if_block_renders_when_truthy(self):
        from llmflows.services.gate import render_step_content
        text = "{% if flow.PR_NUMBER %}PR: #{{flow.PR_NUMBER}}{% endif %}"
        variables = {"flow.PR_NUMBER": "42"}
        result = render_step_content(text, variables)
        assert result == "PR: #42"

    def test_if_block_omitted_when_empty(self):
        from llmflows.services.gate import render_step_content
        text = "Start{% if flow.PR_NUMBER %} PR: #{{flow.PR_NUMBER}}{% endif %} End"
        variables = {"flow.PR_NUMBER": ""}
        result = render_step_content(text, variables)
        assert result == "Start End"

    def test_if_block_omitted_when_undefined(self):
        from llmflows.services.gate import render_step_content
        text = "Start{% if flow.PR_NUMBER %} PR: #{{flow.PR_NUMBER}}{% endif %} End"
        variables = {"flow.ISSUE_NUMBER": "27"}
        result = render_step_content(text, variables)
        assert result == "Start End"

    def test_undefined_variable_renders_empty(self):
        from llmflows.services.gate import render_step_content
        text = "Value: {{flow.MISSING}}"
        variables = {"flow.ISSUE_NUMBER": "27"}
        result = render_step_content(text, variables)
        assert result == "Value: "

    def test_nested_dotted_keys(self):
        from llmflows.services.gate import render_step_content
        text = "Run {{run.id}} in {{step.dir}}"
        variables = {"run.id": "abc", "step.dir": "/tmp/step"}
        result = render_step_content(text, variables)
        assert result == "Run abc in /tmp/step"

    def test_if_elif_else(self):
        from llmflows.services.gate import render_step_content
        text = "{% if flow.PR_NUMBER %}PR{% elif flow.ISSUE_NUMBER %}Issue{% else %}None{% endif %}"
        result1 = render_step_content(text, {"flow.PR_NUMBER": "5"})
        assert result1 == "PR"
        result2 = render_step_content(text, {"flow.ISSUE_NUMBER": "10"})
        assert result2 == "Issue"
        result3 = render_step_content(text, {})
        assert result3 == "None"


class TestRunService:
    def test_enqueue(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("enqueue-flow", space_id=test_space.id)

        run = run_svc.enqueue(test_space.id, flow.id)
        assert run.flow_id == flow.id
        assert run.started_at is None
        assert run.status == "queued"

    def test_get_pending(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("pending-flow", space_id=test_space.id)
        run_svc.enqueue(test_space.id, flow.id)

        pending = run_svc.get_pending(test_space.id)
        assert pending is not None

    def test_mark_started(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("start-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)

        run_svc.mark_started(run.id)
        assert run.started_at is not None
        assert run.status == "running"

    def test_update_run_step(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("step-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        run_svc.update_run_step(run.id, "research", "step-flow")
        assert run.current_step == "research"
        completed = json.loads(run.steps_completed)
        assert "research" in completed

    def test_create_step_run(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("step-run-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "research", 0, "step-run-flow", "pi", "anthropic/claude-sonnet-4-6")
        assert sr.id is not None
        assert sr.step_name == "research"
        assert sr.agent == "pi"
        assert sr.started_at is not None

    def test_mark_step_completed(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("step-complete-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "research", 0, "step-complete-flow")
        run_svc.mark_step_completed(sr.id, "completed")
        test_db.refresh(sr)
        assert sr.completed_at is not None
        assert sr.outcome == "completed"

    def test_get_active_step(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("active-step-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "research", 0, "active-step-flow")
        active = run_svc.get_active_step(run.id)
        assert active is not None
        assert active.id == sr.id

    def test_cancel_run_kills_container(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("cancel-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)
        run.container_id = "deadbeef"
        test_db.commit()

        with patch("llmflows.services.container.kill_run_container", return_value=True) as mock_kill:
            cancelled, killed = run_svc.cancel_run(run.id)

        assert killed is True
        mock_kill.assert_called_once_with("deadbeef")
        assert cancelled.completed_at is not None
        assert cancelled.outcome == "cancelled"
        assert cancelled.container_id is None

    def test_list_step_runs(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("list-steps-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        run_svc.create_step_run(run.id, "research", 0, "list-steps-flow")
        run_svc.create_step_run(run.id, "implement", 1, "list-steps-flow")
        steps = run_svc.list_step_runs(run.id)
        assert len(steps) == 2
        assert steps[0].step_name == "research"
        assert steps[1].step_name == "implement"

    def test_mark_completed(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("complete-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        run_svc.mark_completed(run.id, outcome="completed")
        assert run.completed_at is not None
        assert run.outcome == "completed"
        assert run.status == "completed"

    def test_mark_completed_failed(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("fail-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        run_svc.mark_completed(run.id, outcome="failed")
        assert run.outcome == "failed"

    def test_list_by_space(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("list-space-flow", space_id=test_space.id)
        run_svc.enqueue(test_space.id, flow.id)
        run_svc.enqueue(test_space.id, flow.id)

        runs = run_svc.list_by_space(test_space.id)
        assert len(runs) == 2

    def test_get_pending_flow_improvement(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("pending-improve-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)

        assert run_svc.get_pending_flow_improvement(flow_id=flow.id) is None

        item = run_svc.create_inbox_item(
            type="flow_improvement",
            reference_id=run.id,
            space_id=test_space.id,
            title="Proposal",
        )
        found = run_svc.get_pending_flow_improvement(flow_id=flow.id)
        assert found is not None
        assert found.id == item.id

        by_name = run_svc.get_pending_flow_improvement(
            flow_name=flow.name, space_id=test_space.id,
        )
        assert by_name is not None
        assert by_name.id == item.id

        run_svc.archive_inbox_item(item.id)
        assert run_svc.get_pending_flow_improvement(flow_id=flow.id) is None


class TestStepRunService:
    def test_step_run_log_and_prompt(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("log-prompt-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "research", 0, "log-prompt-flow")
        run_svc.set_step_log_path(sr.id, "/tmp/test.log")
        run_svc.set_step_prompt(sr.id, "# Do research")
        test_db.refresh(sr)
        assert sr.log_path == "/tmp/test.log"
        assert sr.prompt == "# Do research"

    def test_get_step_run(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("get-step-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "research", 0, "get-step-flow")
        fetched = run_svc.get_step_run(sr.id)
        assert fetched is not None
        assert fetched.step_name == "research"

    def test_step_run_to_dict(self, test_db, test_space):
        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)
        flow = flow_svc.create("to-dict-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "research", 0, "to-dict-flow", "pi", "anthropic/claude-sonnet-4-6")
        d = sr.to_dict()
        assert d["step_name"] == "research"
        assert d["agent"] == "pi"
        assert d["model"] == "anthropic/claude-sonnet-4-6"
        assert d["status"] == "running"


class TestFlowVersioning:
    def test_save_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("versioned", space_id=test_space.id, steps=[
            {"name": "research", "position": 0, "content": "# Research"},
        ])
        assert flow.version == 1

        version = svc.save_version(flow.id, description="initial save")
        assert version is not None
        assert version.version == 1
        assert version.description == "initial save"
        test_db.refresh(flow)
        assert flow.version == 2

    def test_add_step_bumps_flow_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("bump-add", space_id=test_space.id)
        assert flow.version == 1
        svc.add_step(flow.id, "research", "# Research")
        test_db.refresh(flow)
        assert flow.version == 2
        versions = svc.list_versions(flow.id)
        assert len(versions) == 1
        assert versions[0].version == 1

    def test_list_versions(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("multi-ver", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0},
        ])
        svc.update_step(flow.steps[0].id, content="updated content")

        versions = svc.list_versions(flow.id)
        assert len(versions) == 1
        assert versions[0].version == 1
        test_db.refresh(flow)
        assert flow.version == 2

    def test_rollback_to_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("rollback-test", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "original content"},
        ])
        v1 = svc.save_version(flow.id, "v1")

        svc.update_step(flow.steps[0].id, content="modified content")
        test_db.refresh(flow)
        assert flow.steps[0].content == "modified content"

        restored = svc.rollback_to_version(flow.id, v1.id)
        assert restored is not None
        test_db.refresh(restored)
        assert len(restored.steps) == 1
        assert restored.steps[0].content == "original content"

    def test_rollback_saves_current_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("rollback-save", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "v1"},
        ])
        v1 = svc.save_version(flow.id, "v1")

        svc.update_step(flow.steps[0].id, content="v2")
        svc.rollback_to_version(flow.id, v1.id)

        versions = svc.list_versions(flow.id)
        assert len(versions) >= 2

    def test_apply_flow_proposal(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("proposal-test", space_id=test_space.id, steps=[
            {"name": "old-step", "position": 0, "content": "old content"},
        ])

        proposal = {
            "name": "proposal-test",
            "version": 2,
            "description": "improved flow",
            "steps": [
                {"name": "new-step-1", "position": 0, "content": "new content 1"},
                {"name": "new-step-2", "position": 1, "content": "new content 2"},
            ],
        }
        result = svc.apply_flow_proposal(flow.id, proposal)
        assert result is not None
        test_db.refresh(result)
        assert result.description == "improved flow"
        assert len(result.steps) == 2
        assert result.steps[0].name == "new-step-1"
        assert result.version == 2

        versions = svc.list_versions(flow.id)
        assert len(versions) == 1
        assert "import" in versions[0].description.lower()

    def test_version_to_dict(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("dict-ver", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0},
        ])
        version = svc.save_version(flow.id, "test version")
        d = version.to_dict()
        assert d["version"] == 1
        assert d["description"] == "test version"
        assert "flow_id" in d
        assert "created_at" in d

    def test_version_snapshot_contains_steps(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("snap-check", space_id=test_space.id, steps=[
            {"name": "research", "position": 0, "content": "# Do research"},
            {"name": "implement", "position": 1, "content": "# Implement"},
        ])
        version = svc.save_version(flow.id)
        snapshot = version.get_snapshot()
        assert snapshot["name"] == "snap-check"
        assert len(snapshot["steps"]) == 2
        assert snapshot["steps"][0]["name"] == "research"

    def test_flow_to_dict_includes_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("ver-dict", space_id=test_space.id)
        d = flow.to_dict()
        assert d["version"] == 1

    def test_rollback_nonexistent_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("bad-rollback", space_id=test_space.id)
        result = svc.rollback_to_version(flow.id, "nonexistent")
        assert result is None

    def test_save_version_nonexistent_flow(self, test_db, test_space):
        svc = FlowService(test_db)
        result = svc.save_version("nonexistent")
        assert result is None

    def test_import_rejects_same_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("ver-reject", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0},
        ])
        assert flow.version == 1

        data = {
            "flows": [{
                "name": "ver-reject",
                "version": 1,
                "steps": [{"name": "step1", "position": 0, "content": "updated"}],
            }]
        }
        with pytest.raises(ValueError, match="already at version 1"):
            svc._import_flows_data(data, space_id=test_space.id)

    def test_import_rejects_lower_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("ver-lower", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0},
        ])
        flow.version = 3
        test_db.commit()

        data = {
            "flows": [{
                "name": "ver-lower",
                "version": 2,
                "steps": [{"name": "step1", "position": 0, "content": "old"}],
            }]
        }
        with pytest.raises(ValueError, match="Import version must be higher"):
            svc._import_flows_data(data, space_id=test_space.id)

    def test_import_rejects_version_after_rollback(self, test_db, test_space):
        """After rollback the flow version is higher, so old versions are still rejected."""
        svc = FlowService(test_db)
        flow = svc.create("ver-hist", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "v1"},
        ])
        v1 = svc.save_version(flow.id, "v1 snapshot")
        test_db.refresh(flow)

        data_v3 = {
            "flows": [{
                "name": "ver-hist",
                "version": 3,
                "steps": [{"name": "step1", "position": 0, "content": "v3"}],
            }]
        }
        svc._import_flows_data(data_v3, space_id=test_space.id)
        test_db.refresh(flow)
        assert flow.version == 3

        svc.rollback_to_version(flow.id, v1.id)
        test_db.refresh(flow)
        assert flow.version > 3

        with pytest.raises(ValueError, match="Import version must be higher"):
            svc._import_flows_data({
                "flows": [{"name": "ver-hist", "version": 3, "steps": []}]
            }, space_id=test_space.id)

    def test_import_accepts_higher_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("ver-accept", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "original"},
        ])

        data = {
            "flows": [{
                "name": "ver-accept",
                "version": 2,
                "steps": [{"name": "step1", "position": 0, "content": "updated"}],
            }]
        }
        count = svc._import_flows_data(data, space_id=test_space.id)
        assert count == 1
        test_db.refresh(flow)
        assert flow.version == 2
        assert flow.steps[0].content == "updated"

        versions = svc.list_versions(flow.id)
        assert len(versions) == 1
        assert versions[0].version == 1

    def test_import_creates_version_snapshot(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("ver-snapshot", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "v1 content"},
        ])

        data = {
            "flows": [{
                "name": "ver-snapshot",
                "version": 2,
                "steps": [{"name": "step1", "position": 0, "content": "v2 content"}],
            }]
        }
        svc._import_flows_data(data, space_id=test_space.id)

        versions = svc.list_versions(flow.id)
        assert len(versions) == 1
        snap = versions[0].get_snapshot()
        assert snap["steps"][0]["content"] == "v1 content"

    def test_import_without_version_rejects_existing(self, test_db, test_space):
        svc = FlowService(test_db)
        svc.create("no-ver-import", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "original"},
        ])

        data = {
            "flows": [{
                "name": "no-ver-import",
                "steps": [{"name": "step1", "position": 0, "content": "updated"}],
            }]
        }
        with pytest.raises(ValueError, match="Import version must be higher"):
            svc._import_flows_data(data, space_id=test_space.id)

    def test_export_includes_version(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("ver-export", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0},
        ])
        flow.version = 3
        test_db.commit()

        data = svc.export_flows(test_space.id)
        flow_data = data["flows"][0]
        assert flow_data["version"] == 3

    def test_import_new_flow_with_version(self, test_db, test_space):
        svc = FlowService(test_db)
        data = {
            "flows": [{
                "name": "brand-new-flow",
                "version": 5,
                "steps": [{"name": "step1", "position": 0}],
            }]
        }
        count = svc._import_flows_data(data, space_id=test_space.id)
        assert count == 1
        flow = svc.get_by_name("brand-new-flow", test_space.id)
        assert flow is not None
        assert flow.version == 5

    def test_apply_proposal_auto_versions(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("auto-ver", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "v1"},
        ])
        assert flow.version == 1

        proposal = {
            "name": "auto-ver",
            "description": "improved",
            "steps": [{"name": "step1", "position": 0, "content": "v2"}],
        }
        result = svc.apply_flow_proposal(flow.id, proposal)
        assert result is not None
        test_db.refresh(result)
        assert result.version == 2


class TestFlowImportAuditCLI:
    """Tests for CLI flow import audit enforcement (issue #25)."""

    def test_cli_import_rejects_unsafe(self, test_db, test_space, temp_dir):
        from click.testing import CliRunner
        from llmflows.cli.flow import flow_import
        from llmflows.services.audit import AuditResult, FlowAuditService

        test_space.audit_flows_on_import = True
        test_db.commit()

        flow_file = temp_dir / "bad.json"
        flow_file.write_text(json.dumps({
            "flows": [{"name": "dangerous", "steps": [{"name": "s1", "position": 0}]}]
        }))

        unsafe = AuditResult(status="unsafe", summary="Exfiltration detected", findings=["sends secrets"])

        runner = CliRunner()
        with (
            patch("llmflows.cli.flow._get_session", return_value=test_db),
            patch("llmflows.cli.flow._resolve_space", return_value=test_space),
            patch.object(FlowAuditService, "run_audit", return_value=unsafe),
        ):
            result = runner.invoke(flow_import, [str(flow_file)])
        assert result.exit_code != 0
        assert "dangerous" in result.output

        svc = FlowService(test_db)
        assert svc.get_by_name("dangerous", test_space.id) is None

    def test_cli_import_succeeds_when_safe(self, test_db, test_space, temp_dir):
        from click.testing import CliRunner
        from llmflows.cli.flow import flow_import
        from llmflows.services.audit import AuditResult, FlowAuditService

        test_space.audit_flows_on_import = True
        test_db.commit()

        flow_file = temp_dir / "good.json"
        flow_file.write_text(json.dumps({
            "flows": [{"name": "safe-flow", "version": 1, "steps": [{"name": "s1", "position": 0}]}]
        }))

        safe = AuditResult(status="safe", summary="All clear")

        runner = CliRunner()
        with (
            patch("llmflows.cli.flow._get_session", return_value=test_db),
            patch("llmflows.cli.flow._resolve_space", return_value=test_space),
            patch.object(FlowAuditService, "run_audit", return_value=safe),
            patch.object(FlowAuditService, "save_audit") as mock_save,
        ):
            result = runner.invoke(flow_import, [str(flow_file)])
        assert result.exit_code == 0
        assert "Imported 1" in result.output
        mock_save.assert_called_once()

    def test_cli_import_skips_audit_when_disabled(self, test_db, test_space, temp_dir):
        from click.testing import CliRunner
        from llmflows.cli.flow import flow_import
        from llmflows.services.audit import FlowAuditService

        test_space.audit_flows_on_import = False
        test_db.commit()

        flow_file = temp_dir / "skip.json"
        flow_file.write_text(json.dumps({
            "flows": [{"name": "skip-flow", "version": 1, "steps": [{"name": "s1", "position": 0}]}]
        }))

        runner = CliRunner()
        with (
            patch("llmflows.cli.flow._get_session", return_value=test_db),
            patch("llmflows.cli.flow._resolve_space", return_value=test_space),
            patch.object(FlowAuditService, "run_audit") as mock_audit,
        ):
            result = runner.invoke(flow_import, [str(flow_file)])
        assert result.exit_code == 0
        mock_audit.assert_not_called()

    def test_cli_import_audit_flag_forces_audit_when_disabled(self, test_db, test_space, temp_dir):
        from click.testing import CliRunner
        from llmflows.cli.flow import flow_import
        from llmflows.services.audit import AuditResult, FlowAuditService

        test_space.audit_flows_on_import = False
        test_db.commit()

        flow_file = temp_dir / "forced.json"
        flow_file.write_text(json.dumps({
            "flows": [{"name": "forced-flow", "version": 1, "steps": [{"name": "s1", "position": 0}]}]
        }))

        safe = AuditResult(status="safe", summary="All clear")

        runner = CliRunner()
        with (
            patch("llmflows.cli.flow._get_session", return_value=test_db),
            patch("llmflows.cli.flow._resolve_space", return_value=test_space),
            patch.object(FlowAuditService, "run_audit", return_value=safe) as mock_audit,
            patch.object(FlowAuditService, "save_audit"),
        ):
            result = runner.invoke(flow_import, [str(flow_file), "--audit"])
        assert result.exit_code == 0
        assert "Running security audit" in result.output
        mock_audit.assert_called_once()

    def test_cli_import_audit_flag_rejects_unsafe(self, test_db, test_space, temp_dir):
        from click.testing import CliRunner
        from llmflows.cli.flow import flow_import
        from llmflows.services.audit import AuditResult, FlowAuditService

        test_space.audit_flows_on_import = False
        test_db.commit()

        flow_file = temp_dir / "bad.json"
        flow_file.write_text(json.dumps({
            "flows": [{"name": "bad-flow", "version": 1, "steps": [{"name": "s1", "position": 0}]}]
        }))

        unsafe = AuditResult(status="unsafe", summary="Exfiltration detected", findings=["sends secrets"])

        runner = CliRunner()
        with (
            patch("llmflows.cli.flow._get_session", return_value=test_db),
            patch("llmflows.cli.flow._resolve_space", return_value=test_space),
            patch.object(FlowAuditService, "run_audit", return_value=unsafe),
        ):
            result = runner.invoke(flow_import, [str(flow_file), "--audit"])
        assert result.exit_code != 0
        assert "bad-flow" in result.output

        svc = FlowService(test_db)
        assert svc.get_by_name("bad-flow", test_space.id) is None


class TestGateRetryExhaustion:
    """When max gate retries are exhausted, the last step_run should reflect the failure."""

    def test_last_retry_gets_gate_failed_outcome(self, test_db, test_space, temp_dir):
        from unittest.mock import patch as _patch
        from llmflows.services.run_daemon import RunDaemon
        from llmflows.services.context import ContextService

        space_path = Path(test_space.path)
        space_path.mkdir(parents=True, exist_ok=True)

        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("retry-flow", space_id=test_space.id, steps=[
            {
                "name": "build",
                "position": 0,
                "content": "# Build",
                "gates": [{"command": "false", "message": "Always fails"}],
                "max_gate_retries": 1,
            },
        ])

        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)
        snapshot = flow_svc.build_flow_snapshot(flow.name, space_id=test_space.id)
        run.flow_snapshot = json.dumps(snapshot)
        test_db.commit()

        artifacts_dir = ContextService.get_artifacts_dir(space_path, run.id, flow.name)
        step_dir = artifacts_dir / "00-build"
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / "_result.md").write_text("attempt done")

        sr1 = run_svc.create_step_run(run.id, "build", 0, flow.name)
        sr1.attempt = 1
        test_db.commit()
        run_svc.mark_step_completed(sr1.id, outcome="completed")

        sr2 = run_svc.create_step_run(run.id, "build", 0, flow.name)
        sr2.attempt = 2
        sr2.prev_gate_failures = json.dumps([{"command": "false", "message": "Always fails", "output": ""}])
        test_db.commit()
        run_svc.mark_step_completed(sr2.id, outcome="completed")

        daemon = RunDaemon.__new__(RunDaemon)
        daemon.run_id = run.id
        daemon._space_id = test_space.id
        daemon._cost_offsets = {}
        daemon.max_log_size_bytes = 500 * 1024 * 1024

        config = {"daemon": {"gate_timeout_seconds": 60}}
        with _patch("llmflows.services.run_daemon.load_system_config", return_value=config), \
             _patch.object(daemon, "_launch_post_run_step"):
            daemon._post_step_completion(
                run, test_space, sr2, space_path, run_svc, flow_svc,
            )

        test_db.refresh(sr2)
        assert sr2.outcome == "gate_failed"

        gf = json.loads(sr2.gate_failures)
        assert len(gf) >= 1
        assert any("Always fails" in f.get("message", "") for f in gf)

    def test_gate_failed_step_run_to_dict(self, test_db, test_space):
        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("dict-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "build", 0, flow.name)
        run_svc.mark_step_completed(sr.id, outcome="gate_failed")
        sr.gate_failures = json.dumps([
            {"command": "false", "message": "Gate check failed", "output": "err"},
        ])
        test_db.commit()
        test_db.refresh(sr)

        d = sr.to_dict()
        assert d["status"] == "gate_failed"
        assert d["outcome"] == "gate_failed"
        assert len(d["gate_failures"]) == 1
        assert d["gate_failures"][0]["message"] == "Gate check failed"

    def test_prev_gate_failures_to_dict(self, test_db, test_space):
        """prev_gate_failures should be exposed in to_dict() separately from gate_failures."""
        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("pgf-flow", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "build", 0, flow.name)
        sr.attempt = 2
        sr.prev_gate_failures = json.dumps([
            {"command": "pytest", "message": "Tests must pass", "output": "FAILED"},
        ])
        test_db.commit()
        test_db.refresh(sr)

        d = sr.to_dict()
        assert d["attempt"] == 2
        assert len(d["prev_gate_failures"]) == 1
        assert d["prev_gate_failures"][0]["message"] == "Tests must pass"
        assert d["gate_failures"] == []

    def test_retry_stores_prev_gate_failures_not_gate_failures(self, test_db, test_space, temp_dir):
        """When _launch_step is called with gate_failures, they should be stored
        in prev_gate_failures on the new step_run, not in gate_failures."""
        from unittest.mock import MagicMock, patch as _patch
        from llmflows.services.run_daemon import RunDaemon
        from llmflows.services.context import ContextService

        space_path = Path(test_space.path)
        space_path.mkdir(parents=True, exist_ok=True)

        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("retry-pgf-flow", space_id=test_space.id, steps=[
            {
                "name": "build",
                "position": 0,
                "content": "# Build",
                "gates": [{"command": "false", "message": "Always fails"}],
                "max_gate_retries": 3,
            },
        ])

        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)
        snapshot = flow_svc.build_flow_snapshot(flow.name, space_id=test_space.id)
        run.flow_snapshot = json.dumps(snapshot)
        test_db.commit()

        daemon = RunDaemon.__new__(RunDaemon)
        daemon.run_id = run.id
        daemon._space_id = test_space.id
        daemon._cost_offsets = {}
        daemon.max_log_size_bytes = 500 * 1024 * 1024

        gate_failures_input = [
            {"command": "false", "message": "Always fails", "output": ""},
        ]

        def fake_executor_launch(ctx):
            result = MagicMock()
            result.success = True
            result.prompt_content = ""
            result.log_path = ""
            result.is_sync = False
            return result

        config = {"daemon": {"gate_timeout_seconds": 60}}
        with _patch("llmflows.services.run_daemon.load_system_config", return_value=config), \
             _patch("llmflows.services.run_daemon.resolve_alias", return_value=("pi", "anthropic/claude-sonnet-4-6")), \
             _patch.object(RunDaemon, "_get_space", return_value=test_space), \
             _patch("llmflows.services.run_daemon.get_executor") as mock_get_exec:
            mock_executor = MagicMock()
            mock_executor.launch = fake_executor_launch
            mock_get_exec.return_value = mock_executor
            daemon._launch_step(
                run, space_path, "build", 0, flow.name,
                run_svc, flow_svc,
                gate_failures=gate_failures_input,
            )

        step_runs = run_svc.list_step_runs(run.id)
        retry_sr = [sr for sr in step_runs if sr.step_name == "build"][-1]
        test_db.refresh(retry_sr)

        assert retry_sr.gate_failures in ("", None)
        pgf = json.loads(retry_sr.prev_gate_failures)
        assert len(pgf) == 1
        assert pgf[0]["message"] == "Always fails"

    def test_unlimited_retries_do_not_exhaust(self, test_db, test_space, temp_dir):
        """When max_gate_retries is 0 (unlimited), the daemon should always retry."""
        from unittest.mock import patch as _patch
        from llmflows.services.run_daemon import RunDaemon
        from llmflows.services.context import ContextService

        space_path = Path(test_space.path)
        space_path.mkdir(parents=True, exist_ok=True)

        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("unlim-flow", space_id=test_space.id, steps=[
            {
                "name": "build",
                "position": 0,
                "content": "# Build",
                "gates": [{"command": "false", "message": "Always fails"}],
                "max_gate_retries": 0,
            },
        ])

        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)
        snapshot = flow_svc.build_flow_snapshot(flow.name, space_id=test_space.id)
        run.flow_snapshot = json.dumps(snapshot)
        test_db.commit()

        artifacts_dir = ContextService.get_artifacts_dir(space_path, run.id, flow.name)
        step_dir = artifacts_dir / "00-build"
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / "_result.md").write_text("done")

        for attempt in range(1, 6):
            sr = run_svc.create_step_run(run.id, "build", 0, flow.name)
            sr.attempt = attempt
            test_db.commit()
            run_svc.mark_step_completed(sr.id, outcome="completed")

        last_sr = run_svc.create_step_run(run.id, "build", 0, flow.name)
        last_sr.attempt = 6
        test_db.commit()
        run_svc.mark_step_completed(last_sr.id, outcome="completed")

        daemon = RunDaemon.__new__(RunDaemon)
        daemon.run_id = run.id
        daemon._space_id = test_space.id
        daemon._cost_offsets = {}
        daemon.max_log_size_bytes = 500 * 1024 * 1024

        config = {"daemon": {"gate_timeout_seconds": 60}}
        with _patch("llmflows.services.run_daemon.load_system_config", return_value=config), \
             _patch.object(daemon, "_launch_step") as mock_launch:
            daemon._post_step_completion(
                run, test_space, last_sr, space_path, run_svc, flow_svc,
            )

        test_db.refresh(last_sr)
        assert last_sr.outcome == "completed"
        mock_launch.assert_called_once()


class TestDaemonTimeout:
    """Tests for daemon timeout logic — HITL exclusion and post-run loop prevention."""

    def _setup_run_with_step(self, test_db, test_space, step_name="agent-step",
                              flow_name="timeout-flow", step_position=0):
        from llmflows.db.models import FlowRun, StepRun, Flow
        from datetime import datetime, timezone
        flow = Flow(name=flow_name, space_id=test_space.id)
        test_db.add(flow)
        test_db.flush()
        run = FlowRun(space_id=test_space.id, flow_id=flow.id)
        run.started_at = datetime.now(timezone.utc)
        test_db.add(run)
        test_db.flush()
        sr = StepRun(
            flow_run_id=run.id, step_name=step_name,
            step_position=step_position, flow_name=flow_name,
            agent="pi", model="test",
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        test_db.add(sr)
        test_db.commit()
        return run, sr, flow

    def test_timeout_marks_run_completed(self, test_db, test_space):
        """When a step times out, the run should be marked completed before post-run launch."""
        from llmflows.services.run_daemon import RunDaemon

        run, sr, flow = self._setup_run_with_step(test_db, test_space)

        daemon = RunDaemon.__new__(RunDaemon)
        daemon.run_id = run.id
        daemon._space_id = test_space.id
        daemon.run_timeout_minutes = 60
        daemon.max_log_size_bytes = 500 * 1024 * 1024
        daemon._cost_offsets = {}

        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)

        with patch.object(RunDaemon, '_get_snapshot_step', return_value={"step_type": "agent"}), \
             patch("llmflows.services.run_daemon.get_executor") as mock_exec, \
             patch("llmflows.services.agent.AgentService.kill_agent"), \
             patch.object(RunDaemon, '_launch_post_run_step'):
            mock_executor = mock_exec.return_value
            mock_executor.is_running.return_value = True

            daemon._process_active_step(
                run, test_space, sr,
                Path(test_space.path),
                run_svc, flow_svc,
            )

        test_db.refresh(run)
        assert run.completed_at is not None
        assert run.outcome == "timeout"

    def test_timeout_skips_post_run_step(self, test_db, test_space):
        """Timeout check should not apply to __post_run__ steps."""
        from llmflows.services.run_daemon import RunDaemon

        run, _, flow = self._setup_run_with_step(
            test_db, test_space, step_name="__post_run__", step_position=2,
        )
        sr = run.step_runs[0]

        daemon = RunDaemon.__new__(RunDaemon)
        daemon.run_id = run.id
        daemon._space_id = test_space.id
        daemon.run_timeout_minutes = 1
        daemon.max_log_size_bytes = 500 * 1024 * 1024
        daemon._cost_offsets = {}

        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)

        with patch.object(RunDaemon, '_get_snapshot_step', return_value={"step_type": "agent"}), \
             patch("llmflows.services.run_daemon.get_executor") as mock_exec, \
             patch("llmflows.services.agent.AgentService.kill_agent") as mock_kill:
            mock_executor = mock_exec.return_value
            mock_executor.is_running.return_value = True

            daemon._process_active_step(
                run, test_space, sr,
                Path(test_space.path),
                run_svc, flow_svc,
            )

        mock_kill.assert_not_called()
        test_db.refresh(run)
        assert run.completed_at is None

    def test_max_spend_skips_post_run_step(self, test_db, test_space):
        """Max spend check should not apply to __post_run__ steps."""
        from llmflows.services.run_daemon import RunDaemon

        run, sr, flow = self._setup_run_with_step(
            test_db, test_space, step_name="__post_run__", step_position=2,
        )
        flow.max_spend_usd = 0.01
        test_db.commit()

        daemon = RunDaemon.__new__(RunDaemon)
        daemon.run_id = run.id
        daemon._space_id = test_space.id
        daemon.run_timeout_minutes = 0
        daemon.max_log_size_bytes = 500 * 1024 * 1024
        daemon._cost_offsets = {}

        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)

        result = daemon._check_max_spend(
            run, test_space, sr,
            Path(test_space.path),
            run_svc, flow_svc,
        )
        assert result is False


class TestPostRunPendingImprovement:
    """Skip successful post-run analysis when a flow improvement is still pending."""

    def test_skips_post_run_when_pending_improvement_exists(self, test_db, test_space):
        from llmflows.services.run_daemon import RunDaemon

        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("skip-post-run-flow", space_id=test_space.id)

        prior = run_svc.enqueue(test_space.id, flow.id)
        run_svc.create_inbox_item(
            type="flow_improvement",
            reference_id=prior.id,
            space_id=test_space.id,
            title="Pending proposal",
        )

        run = run_svc.enqueue(test_space.id, flow.id)

        daemon = RunDaemon.__new__(RunDaemon)
        daemon.run_id = run.id
        daemon._space_id = test_space.id

        with patch.object(RunDaemon, "_get_space", return_value=test_space), \
             patch("llmflows.services.agent.AgentService.prepare_and_launch_step") as mock_launch:
            daemon._launch_post_run_step(
                run, Path(test_space.path), 1, run_svc, flow_svc,
            )

        mock_launch.assert_not_called()
        assert run_svc.get_latest_step_run(run.id, "__post_run__") is None

    def test_still_launches_post_run_on_error_with_pending(self, test_db, test_space):
        from llmflows.services.run_daemon import RunDaemon

        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("error-post-run-flow", space_id=test_space.id)

        prior = run_svc.enqueue(test_space.id, flow.id)
        run_svc.create_inbox_item(
            type="flow_improvement",
            reference_id=prior.id,
            space_id=test_space.id,
            title="Pending proposal",
        )

        run = run_svc.enqueue(test_space.id, flow.id)
        run.outcome = "error"
        test_db.commit()

        daemon = RunDaemon.__new__(RunDaemon)
        daemon.run_id = run.id
        daemon._space_id = test_space.id

        with patch.object(RunDaemon, "_get_space", return_value=test_space), \
             patch("llmflows.services.run_daemon.resolve_alias", return_value=("pi", "mini-model")), \
             patch("llmflows.services.run_daemon.load_system_config", return_value={"daemon": {}}), \
             patch("llmflows.services.agent.AgentService.prepare_and_launch_step",
                   return_value=(True, "prompt", "/tmp/log")) as mock_launch, \
             patch("llmflows.services.audit.FlowAuditService.get_audit", return_value=None):
            daemon._launch_post_run_step(
                run, Path(test_space.path), 1, run_svc, flow_svc,
                error_context={
                    "failed_step": "build",
                    "error_details": "boom",
                    "log_tail": "error",
                },
            )

        mock_launch.assert_called_once()
        assert run_svc.get_latest_step_run(run.id, "__post_run__") is not None


class TestChannelManagerMute:
    def test_notify_suppressed_when_muted(self):
        from llmflows.services.gateway.channel import ChannelManager
        from unittest.mock import MagicMock

        ch = MagicMock()
        ch.name = "test"
        ch.subscribed_events = ["run.completed"]
        mgr = ChannelManager()
        mgr.register(ch)

        muted_config = {"daemon": {"inbox_muted": True}}
        with patch("llmflows.config.load_system_config", return_value=muted_config):
            mgr.notify("run.completed", {"flow_name": "test"})

        ch.send.assert_not_called()

    def test_notify_sent_when_not_muted(self):
        from llmflows.services.gateway.channel import ChannelManager
        from unittest.mock import MagicMock

        ch = MagicMock()
        ch.name = "test"
        ch.subscribed_events = ["run.completed"]
        mgr = ChannelManager()
        mgr.register(ch)

        unmuted_config = {"daemon": {"inbox_muted": False}}
        with patch("llmflows.config.load_system_config", return_value=unmuted_config):
            mgr.notify("run.completed", {"flow_name": "test"})

        ch.send.assert_called_once_with("run.completed", {"flow_name": "test"})

    def test_notify_sent_when_no_mute_key(self):
        from llmflows.services.gateway.channel import ChannelManager
        from unittest.mock import MagicMock

        ch = MagicMock()
        ch.name = "test"
        ch.subscribed_events = ["step.awaiting_user"]
        mgr = ChannelManager()
        mgr.register(ch)

        with patch("llmflows.config.load_system_config", return_value={"daemon": {}}):
            mgr.notify("step.awaiting_user", {"step_name": "ask"})

        ch.send.assert_called_once()


class TestKeepAwake:
    """Tests for the keep_awake feature (macOS caffeinate + Linux systemd-inhibit)."""

    def test_start_keep_awake_disabled(self):
        from llmflows.services.daemon import Daemon

        daemon = Daemon.__new__(Daemon)
        daemon.config = {"daemon": {"keep_awake": False}}
        daemon._keep_awake_proc = None

        with patch("llmflows.services.daemon.subprocess") as mock_sub:
            daemon._start_keep_awake()

        mock_sub.Popen.assert_not_called()
        assert daemon._keep_awake_proc is None

    def test_start_keep_awake_on_darwin(self):
        from llmflows.services.daemon import Daemon
        from unittest.mock import MagicMock

        daemon = Daemon.__new__(Daemon)
        daemon.config = {"daemon": {"keep_awake": True}}
        daemon._keep_awake_proc = None

        mock_proc = MagicMock()
        mock_proc.pid = 12345

        with patch("llmflows.services.daemon.sys") as mock_sys, \
             patch("llmflows.services.daemon.subprocess") as mock_sub:
            mock_sys.platform = "darwin"
            mock_sub.Popen.return_value = mock_proc
            mock_sub.DEVNULL = subprocess.DEVNULL
            daemon._start_keep_awake()

        mock_sub.Popen.assert_called_once_with(
            ["caffeinate", "-s", "-i"],
            stdout=mock_sub.DEVNULL,
            stderr=mock_sub.DEVNULL,
        )
        assert daemon._keep_awake_proc is mock_proc

    def test_start_keep_awake_on_linux(self):
        from llmflows.services.daemon import Daemon
        from unittest.mock import MagicMock

        daemon = Daemon.__new__(Daemon)
        daemon.config = {"daemon": {"keep_awake": True}}
        daemon._keep_awake_proc = None

        mock_proc = MagicMock()
        mock_proc.pid = 54321

        with patch("llmflows.services.daemon.sys") as mock_sys, \
             patch("llmflows.services.daemon.subprocess") as mock_sub:
            mock_sys.platform = "linux"
            mock_sub.Popen.return_value = mock_proc
            mock_sub.DEVNULL = subprocess.DEVNULL
            daemon._start_keep_awake()

        mock_sub.Popen.assert_called_once_with(
            [
                "systemd-inhibit",
                "--what=idle:sleep",
                "--who=llmflows",
                "--why=Daemon is running",
                "--mode=block",
                "sleep", "infinity",
            ],
            stdout=mock_sub.DEVNULL,
            stderr=mock_sub.DEVNULL,
        )
        assert daemon._keep_awake_proc is mock_proc

    def test_start_keep_awake_unsupported_platform(self):
        from llmflows.services.daemon import Daemon

        daemon = Daemon.__new__(Daemon)
        daemon.config = {"daemon": {"keep_awake": True}}
        daemon._keep_awake_proc = None

        with patch("llmflows.services.daemon.sys") as mock_sys, \
             patch("llmflows.services.daemon.subprocess") as mock_sub:
            mock_sys.platform = "win32"
            daemon._start_keep_awake()

        mock_sub.Popen.assert_not_called()
        assert daemon._keep_awake_proc is None

    def test_start_keep_awake_binary_not_found(self):
        from llmflows.services.daemon import Daemon

        daemon = Daemon.__new__(Daemon)
        daemon.config = {"daemon": {"keep_awake": True}}
        daemon._keep_awake_proc = None

        with patch("llmflows.services.daemon.sys") as mock_sys, \
             patch("llmflows.services.daemon.subprocess") as mock_sub:
            mock_sys.platform = "darwin"
            mock_sub.Popen.side_effect = FileNotFoundError
            mock_sub.DEVNULL = subprocess.DEVNULL
            daemon._start_keep_awake()

        assert daemon._keep_awake_proc is None

    def test_start_keep_awake_linux_binary_not_found(self):
        from llmflows.services.daemon import Daemon

        daemon = Daemon.__new__(Daemon)
        daemon.config = {"daemon": {"keep_awake": True}}
        daemon._keep_awake_proc = None

        with patch("llmflows.services.daemon.sys") as mock_sys, \
             patch("llmflows.services.daemon.subprocess") as mock_sub:
            mock_sys.platform = "linux"
            mock_sub.Popen.side_effect = FileNotFoundError
            mock_sub.DEVNULL = subprocess.DEVNULL
            daemon._start_keep_awake()

        assert daemon._keep_awake_proc is None

    def test_keep_awake_command_darwin(self):
        from llmflows.services.daemon import Daemon

        with patch("llmflows.services.daemon.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert Daemon._keep_awake_command() == ["caffeinate", "-s", "-i"]

    def test_keep_awake_command_linux(self):
        from llmflows.services.daemon import Daemon

        with patch("llmflows.services.daemon.sys") as mock_sys:
            mock_sys.platform = "linux"
            cmd = Daemon._keep_awake_command()
            assert cmd[0] == "systemd-inhibit"
            assert "sleep" in cmd

    def test_keep_awake_command_unsupported(self):
        from llmflows.services.daemon import Daemon

        with patch("llmflows.services.daemon.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert Daemon._keep_awake_command() is None

    def test_stop_keep_awake(self):
        from llmflows.services.daemon import Daemon
        from unittest.mock import MagicMock

        daemon = Daemon.__new__(Daemon)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        daemon._keep_awake_proc = mock_proc

        daemon._stop_keep_awake()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=2)
        assert daemon._keep_awake_proc is None

    def test_stop_keep_awake_already_dead(self):
        from llmflows.services.daemon import Daemon
        from unittest.mock import MagicMock

        daemon = Daemon.__new__(Daemon)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        daemon._keep_awake_proc = mock_proc

        daemon._stop_keep_awake()

        mock_proc.terminate.assert_not_called()
        assert daemon._keep_awake_proc is None

    def test_stop_keep_awake_none(self):
        from llmflows.services.daemon import Daemon

        daemon = Daemon.__new__(Daemon)
        daemon._keep_awake_proc = None
        daemon._stop_keep_awake()
        assert daemon._keep_awake_proc is None


class TestDaemonContainerCommit:
    def test_commits_runner_image_for_completed_run_with_container(self, test_db, test_space):
        """RunDaemon marks runs completed before the container exits."""
        from unittest.mock import patch

        from llmflows.services.daemon import Daemon
        from llmflows.services.flow import FlowService
        from llmflows.services.run import RunService

        flow_svc = FlowService(test_db)
        flow = flow_svc.create("news", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "# Step"},
        ])
        run_svc = RunService(test_db)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)
        run_svc.mark_completed(run.id, outcome="completed")
        run.container_id = "deadbeefcafe"
        test_db.commit()

        daemon = Daemon()
        with patch("llmflows.services.container.is_container_alive", return_value=False), \
             patch("llmflows.services.container.get_container_exit_code", return_value=0), \
             patch("llmflows.services.container.commit_container_to_flow_image", return_value=(True, "")) as commit, \
             patch("llmflows.services.container.remove_container", return_value=True), \
             patch.object(daemon, "_handle_completed_run_notifications"), \
             patch.object(daemon, "_maybe_create_improvement_inbox"), \
             patch.object(daemon, "_finalize_run"):
            daemon._process_space(test_space, run_svc, flow_svc)

        commit.assert_called_once_with("deadbeefcafe", flow.id, 1)
        test_db.refresh(run)
        assert run.container_id is None

    def test_processes_second_exited_container_after_first_commit(self, test_db, test_space):
        """Re-fetching by ID must work after session commits from prior runs."""
        from unittest.mock import patch

        from llmflows.services.daemon import Daemon
        from llmflows.services.flow import FlowService
        from llmflows.services.run import RunService

        flow_svc = FlowService(test_db)
        flow = flow_svc.create("multi", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0, "content": "# Step"},
        ])
        run_svc = RunService(test_db)
        run1 = run_svc.enqueue(test_space.id, flow.id)
        run2 = run_svc.enqueue(test_space.id, flow.id)
        for run in (run1, run2):
            run_svc.mark_started(run.id)
            run_svc.mark_completed(run.id, outcome="completed")
            run.container_id = f"deadbeef{run.id[:4]}"
        test_db.commit()

        daemon = Daemon()
        with patch("llmflows.services.container.is_container_alive", return_value=False), \
             patch("llmflows.services.container.get_container_exit_code", return_value=0), \
             patch("llmflows.services.container.commit_container_to_flow_image", return_value=(True, "")) as commit, \
             patch("llmflows.services.container.remove_container", return_value=True), \
             patch.object(daemon, "_handle_completed_run_notifications"), \
             patch.object(daemon, "_maybe_create_improvement_inbox"), \
             patch.object(daemon, "_finalize_run"):
            daemon._process_space(test_space, run_svc, flow_svc)

        assert commit.call_count == 2
        test_db.refresh(run1)
        test_db.refresh(run2)
        assert run1.container_id is None
        assert run2.container_id is None


class TestChatContainerEnv:
    def test_build_chat_container_env_includes_space_host_path(self):
        from llmflows.services.chat import build_chat_container_env

        env = build_chat_container_env("/Users/me/personal")
        assert env["LLMFLOWS_SPACE_HOST_PATH"] == str(Path("/Users/me/personal").resolve())

    def test_build_chat_container_env_omits_space_host_path_without_space(self):
        from llmflows.services.chat import build_chat_container_env

        env = build_chat_container_env()
        assert "LLMFLOWS_SPACE_HOST_PATH" not in env

    def test_build_chat_container_env_sets_pythonpath_in_dev(self, monkeypatch):
        from llmflows.services.chat import build_chat_container_env
        from llmflows.services.container import DEV_CONTAINER_PYTHONPATH

        monkeypatch.setenv("LLMFLOWS_DEV_HOME", "/tmp/.llmflows")
        env = build_chat_container_env()
        assert env["PYTHONPATH"] == DEV_CONTAINER_PYTHONPATH

    def test_build_pi_mcp_env_includes_selected_connectors(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.chat import build_pi_mcp_env

        test_db.add(McpConnector(
            server_id="browser",
            name="Browser",
            command="tsx mcp-server-browser.ts",
            enabled=True,
            builtin=True,
        ))
        test_db.commit()

        with patch("llmflows.db.database.get_session", return_value=test_db):
            env = build_pi_mcp_env(["browser"])

        assert "MCP_SERVERS" in env
        servers = json.loads(env["MCP_SERVERS"])
        assert len(servers) == 1
        assert servers[0]["server_id"] == "browser"

    def test_build_pi_mcp_env_empty_when_no_connectors_selected(self):
        from llmflows.services.chat import build_pi_mcp_env

        assert build_pi_mcp_env([]) == {}

    def test_build_pi_mcp_env_runner_sets_host_browser_mode(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.chat import build_pi_mcp_env

        test_db.add(McpConnector(
            server_id="browser",
            name="Browser",
            command="tsx mcp-server-browser.ts",
            enabled=True,
            builtin=True,
            env='{"BROWSER_HEADLESS": "false"}',
        ))
        test_db.commit()

        with patch("llmflows.db.database.get_session", return_value=test_db):
            env = build_pi_mcp_env(["browser"], runner=True)

        servers = json.loads(env["MCP_SERVERS"])
        assert servers[0]["env"]["BROWSER_MODE"] == "host"
        assert servers[0]["env"]["BROWSER_HEADLESS"] == "false"

    def test_get_mcp_servers_runner_uses_container_paths(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.mcp import get_mcp_servers

        test_db.add(McpConnector(
            server_id="browser",
            name="Browser",
            command="tsx mcp-server-browser.ts",
            enabled=True,
            builtin=True,
            env='{"BROWSER_HEADLESS": "false"}',
        ))
        test_db.commit()

        with patch("llmflows.db.database.get_session", return_value=test_db), \
             patch("llmflows.services.mcp.docker_host_gateway_ip", return_value="192.168.5.2"):
            servers = get_mcp_servers(["browser"], runner=True)

        entry = servers[0]
        assert entry["command"] == "/opt/llmflows/tools/node_modules/.bin/tsx"
        assert entry["args"] == ["/opt/llmflows/llmflows/tools/mcp-server-browser.ts"]
        assert entry["env"]["NODE_PATH"] == "/opt/llmflows/tools/node_modules"
        assert entry["env"]["LLMFLOWS_RUNNER"] == "1"
        assert entry["env"]["BROWSER_CDP_HOST"] == "192.168.5.2"

    def test_notion_connector_maps_legacy_api_key_to_token(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.mcp import get_mcp_servers

        test_db.add(McpConnector(
            server_id="notion",
            name="Notion",
            command="npx @notionhq/notion-mcp-server",
            enabled=True,
            credentials='{"NOTION_API_KEY": "ntn_legacy"}',
        ))
        test_db.commit()

        with patch("llmflows.db.database.get_session", return_value=test_db):
            servers = get_mcp_servers(["notion"])

        assert servers[0]["env"]["NOTION_TOKEN"] == "ntn_legacy"
        assert "NOTION_API_KEY" not in servers[0]["env"]

    def test_github_connector_passes_personal_access_token(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.mcp import get_mcp_servers

        test_db.add(McpConnector(
            server_id="github",
            name="GitHub",
            command="npx @modelcontextprotocol/server-github",
            enabled=True,
            credentials='{"GITHUB_PERSONAL_ACCESS_TOKEN": "gho_test"}',
        ))
        test_db.commit()

        with patch("llmflows.db.database.get_session", return_value=test_db):
            servers = get_mcp_servers(["github"])

        assert servers[0]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "gho_test"
        assert "GITHUB_TOKEN" not in servers[0]["env"]

    def test_github_connector_does_not_map_legacy_token_key(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.mcp import get_mcp_servers

        test_db.add(McpConnector(
            server_id="github",
            name="GitHub",
            command="npx @modelcontextprotocol/server-github",
            enabled=True,
            credentials='{"GITHUB_TOKEN": "gho_legacy"}',
        ))
        test_db.commit()

        with patch("llmflows.db.database.get_session", return_value=test_db):
            servers = get_mcp_servers(["github"])

        assert servers[0]["env"].get("GITHUB_TOKEN") == "gho_legacy"
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in servers[0]["env"]

    def test_build_pi_mcp_env_runner_keeps_headless_when_configured(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.chat import build_pi_mcp_env

        test_db.add(McpConnector(
            server_id="browser",
            name="Browser",
            command="tsx mcp-server-browser.ts",
            enabled=True,
            builtin=True,
            env='{"BROWSER_HEADLESS": "true"}',
        ))
        test_db.commit()

        with patch("llmflows.db.database.get_session", return_value=test_db):
            env = build_pi_mcp_env(["browser"], runner=True)

        servers = json.loads(env["MCP_SERVERS"])
        assert "BROWSER_MODE" not in servers[0]["env"]
        assert servers[0]["env"]["BROWSER_HEADLESS"] == "true"


class TestBrowserHostConnectors:
    def test_connectors_need_host_browser_with_headed_config(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.browser_host import connectors_need_host_browser

        test_db.add(McpConnector(
            server_id="browser",
            name="Browser",
            command="tsx mcp-server-browser.ts",
            enabled=True,
            builtin=True,
            env='{"BROWSER_HEADLESS": "false"}',
        ))
        test_db.commit()

        assert connectors_need_host_browser(["browser"], test_db) is True
        assert connectors_need_host_browser(["web_search"], test_db) is False
        assert connectors_need_host_browser(["browser-host"], test_db) is True

    def test_connectors_need_host_browser_respects_headless_config(self, test_db):
        from llmflows.db.models import McpConnector
        from llmflows.services.browser_host import connectors_need_host_browser

        test_db.add(McpConnector(
            server_id="browser",
            name="Browser",
            command="tsx mcp-server-browser.ts",
            enabled=True,
            builtin=True,
            env='{"BROWSER_HEADLESS": "true"}',
        ))
        test_db.commit()

        assert connectors_need_host_browser(["browser"], test_db) is False
