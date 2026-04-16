"""Tests for service layer."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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
        assert space.path == "/tmp/test"

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
        assert data["version"] == 1
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

        sr = run_svc.create_step_run(run.id, "research", 0, "step-run-flow", "cursor", "auto")
        assert sr.id is not None
        assert sr.step_name == "research"
        assert sr.agent == "cursor"
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

        sr = run_svc.create_step_run(run.id, "research", 0, "to-dict-flow", "cursor", "auto")
        d = sr.to_dict()
        assert d["step_name"] == "research"
        assert d["agent"] == "cursor"
        assert d["model"] == "auto"
        assert d["status"] == "running"
