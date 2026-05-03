"""Tests for service layer."""

import json
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

    def test_list_versions(self, test_db, test_space):
        svc = FlowService(test_db)
        flow = svc.create("multi-ver", space_id=test_space.id, steps=[
            {"name": "step1", "position": 0},
        ])
        svc.save_version(flow.id, "v1 save")
        svc.update_step(flow.steps[0].id, content="updated content")
        svc.save_version(flow.id, "v2 save")

        versions = svc.list_versions(flow.id)
        assert len(versions) == 2
        assert versions[0].version == 2
        assert versions[1].version == 1

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


<class TestGateRetryExhaustion:
    """When max gate retries are exhausted, the last step_run should reflect the failure."""

    def test_last_retry_gets_gate_failed_outcome(self, test_db, test_space, temp_dir):
        from unittest.mock import MagicMock, patch as _patch
        from llmflows.services.daemon import Daemon
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
        sr2.gate_failures = json.dumps([{"command": "false", "message": "Always fails", "output": ""}])
        test_db.commit()
        run_svc.mark_step_completed(sr2.id, outcome="completed")

        daemon = Daemon.__new__(Daemon)
        daemon._browser_active_runs = set()
        daemon.notifications = MagicMock()

        config = {"daemon": {"gate_timeout_seconds": 60}}
        with _patch("llmflows.services.daemon.load_system_config", return_value=config), \
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

    def test_unlimited_retries_do_not_exhaust(self, test_db, test_space, temp_dir):
        """When max_gate_retries is 0 (unlimited), the daemon should always retry."""
        from unittest.mock import MagicMock, patch as _patch
        from llmflows.services.daemon import Daemon
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

        daemon = Daemon.__new__(Daemon)
        daemon._browser_active_runs = set()
        daemon.notifications = MagicMock()

        config = {"daemon": {"gate_timeout_seconds": 60}}
        with _patch("llmflows.services.daemon.load_system_config", return_value=config), \
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
        from llmflows.services.daemon import Daemon
        from llmflows.db.models import FlowRun

        run, sr, flow = self._setup_run_with_step(test_db, test_space)

        daemon = Daemon.__new__(Daemon)
        daemon.run_timeout_minutes = 60
        daemon._browser_active_runs = set()
        daemon.notifications = type("Noop", (), {"notify": lambda *a, **k: None})()

        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)

        with patch.object(Daemon, '_get_snapshot_step', return_value={"step_type": "agent"}), \
             patch("llmflows.services.daemon.get_executor") as mock_exec, \
             patch("llmflows.services.agent.AgentService.kill_agent"), \
             patch.object(Daemon, '_launch_post_run_step'):
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
        from llmflows.services.daemon import Daemon

        run, _, flow = self._setup_run_with_step(
            test_db, test_space, step_name="__post_run__", step_position=2,
        )
        sr = run.step_runs[0]

        daemon = Daemon.__new__(Daemon)
        daemon.run_timeout_minutes = 1
        daemon._browser_active_runs = set()
        daemon.notifications = type("Noop", (), {"notify": lambda *a, **k: None})()

        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)

        with patch.object(Daemon, '_get_snapshot_step', return_value={"step_type": "agent"}), \
             patch("llmflows.services.daemon.get_executor") as mock_exec, \
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
        from llmflows.services.daemon import Daemon
        from llmflows.db.models import Flow

        run, sr, flow = self._setup_run_with_step(
            test_db, test_space, step_name="__post_run__", step_position=2,
        )
        flow.max_spend_usd = 0.01
        test_db.commit()

        daemon = Daemon.__new__(Daemon)
        daemon.run_timeout_minutes = 0
        daemon._browser_active_runs = set()

        run_svc = RunService(test_db)
        flow_svc = FlowService(test_db)

        result = daemon._check_max_spend(
            run, test_space, sr,
            Path(test_space.path),
            run_svc, flow_svc,
        )
        assert result is False



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
