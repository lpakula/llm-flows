"""Tests for service layer."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from llmflows.db.models import  FlowStep, TaskType
from llmflows.services.agent import AgentService
from llmflows.services.flow import FlowService
from llmflows.services.gate import evaluate_gates
from llmflows.services.project import ProjectService
from llmflows.services.run import RunService
from llmflows.services.task import TaskService


class TestProjectService:
    def test_register(self, test_db):
        svc = ProjectService(test_db)
        project = svc.register("test", "/tmp/test")
        assert project.name == "test"
        assert project.path == "/tmp/test"

    def test_register_idempotent(self, test_db):
        svc = ProjectService(test_db)
        p1 = svc.register("test", "/tmp/test")
        p2 = svc.register("test", "/tmp/test")
        assert p1.id == p2.id

    def test_unregister(self, test_db):
        svc = ProjectService(test_db)
        project = svc.register("test", "/tmp/test")
        assert svc.unregister(project.id) is True
        assert svc.get(project.id) is None

    def test_unregister_nonexistent(self, test_db):
        svc = ProjectService(test_db)
        assert svc.unregister("nope") is False

    def test_list_all(self, test_db):
        svc = ProjectService(test_db)
        svc.register("a", "/tmp/a")
        svc.register("b", "/tmp/b")
        assert len(svc.list_all()) == 2

    def test_get_by_path(self, test_db):
        svc = ProjectService(test_db)
        svc.register("test", "/tmp/test")
        found = svc.get_by_path("/tmp/test")
        assert found is not None
        assert found.name == "test"

    def test_get_by_path_not_found(self, test_db):
        svc = ProjectService(test_db)
        assert svc.get_by_path("/tmp/nope") is None


class TestTaskService:
    def test_create(self, test_db, test_project):
        svc = TaskService(test_db)
        task = svc.create(test_project.id, "Test task", description="A description")
        assert task.name == "Test task"
        assert task.description == "A description"
        assert task.project_id == test_project.id

    def test_create_with_options(self, test_db, test_project):
        svc = TaskService(test_db)
        task = svc.create(
            test_project.id,
            "Fix the bug",
            description="It crashes on Safari",
            task_type=TaskType.FIX,
        )
        assert task.name == "Fix the bug"
        assert task.type == TaskType.FIX

    def test_list_by_project(self, test_db, test_project):
        svc = TaskService(test_db)
        svc.create(test_project.id, "Task 1")
        svc.create(test_project.id, "Task 2")
        tasks = svc.list_by_project(test_project.id)
        assert len(tasks) == 2

    def test_update_fields(self, test_db, test_project):
        svc = TaskService(test_db)
        task = svc.create(test_project.id, "Test")
        svc.update(task.id, worktree_branch="task-abc123")
        updated = svc.get(task.id)
        assert updated.worktree_branch == "task-abc123"

    def test_delete(self, test_db, test_project):
        svc = TaskService(test_db)
        task = svc.create(test_project.id, "Delete me")
        assert svc.delete(task.id) is True
        assert svc.get(task.id) is None

    def test_delete_nonexistent(self, test_db, test_project):
        svc = TaskService(test_db)
        assert svc.delete("nope") is False


class TestFlowService:
    def test_create_flow(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("test-flow", description="A test flow")
        assert flow.name == "test-flow"
        assert flow.description == "A test flow"

    def test_create_flow_with_steps(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("with-steps", steps=[
            {"name": "research", "position": 0, "content": "# Research"},
            {"name": "execute", "position": 1, "content": "# Execute"},
        ])
        assert len(flow.steps) == 2
        assert flow.steps[0].name == "research"

    def test_create_flow_duplicate_name(self, test_db):
        import pytest
        svc = FlowService(test_db)
        svc.create("dup-test")
        with pytest.raises(ValueError, match="already exists"):
            svc.create("dup-test")

    def test_get_by_name(self, test_db):
        svc = FlowService(test_db)
        svc.create("lookup")
        found = svc.get_by_name("lookup")
        assert found is not None
        assert found.name == "lookup"

    def test_list_all(self, test_db):
        svc = FlowService(test_db)
        svc.create("flow-a")
        svc.create("flow-b")
        flows = svc.list_all()
        assert len(flows) == 2

    def test_update(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("update-test", description="Old")
        svc.update(flow.id, description="New")
        updated = svc.get(flow.id)
        assert updated.description == "New"

    def test_delete(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("delete-me")
        assert svc.delete(flow.id) is True
        assert svc.get(flow.id) is None

    def test_delete_default_flow_raises(self, test_db):
        import pytest
        svc = FlowService(test_db)
        flow = svc.create("default")
        with pytest.raises(ValueError, match="Cannot delete"):
            svc.delete(flow.id)

    def test_add_step(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("step-test")
        step = svc.add_step(flow.id, "research", "# Research content")
        assert step.name == "research"
        assert step.content == "# Research content"

    def test_update_step(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("step-update")
        step = svc.add_step(flow.id, "test", "old content")
        svc.update_step(step.id, content="new content")
        updated = test_db.query(FlowStep).filter_by(id=step.id).first()
        assert updated.content == "new content"

    def test_remove_step(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("step-remove")
        step = svc.add_step(flow.id, "test", "content")
        assert svc.remove_step(step.id) is True
        assert test_db.query(FlowStep).filter_by(id=step.id).first() is None

    def test_reorder_steps(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("reorder")
        s1 = svc.add_step(flow.id, "a", "", 0)
        s2 = svc.add_step(flow.id, "b", "", 1)
        s3 = svc.add_step(flow.id, "c", "", 2)
        svc.reorder_steps(flow.id, [s3.id, s1.id, s2.id])
        flow = svc.get(flow.id)
        names = [s.name for s in sorted(flow.steps, key=lambda s: s.position)]
        assert names == ["c", "a", "b"]

    def test_get_step_content(self, test_db):
        svc = FlowService(test_db)
        svc.create("content-test", steps=[
            {"name": "research", "content": "# Do Research"},
        ])
        content = svc.get_step_content("content-test", "research")
        assert content.startswith("# Do Research")
        assert "llmflows mode next" in content

    def test_get_step_content_not_found(self, test_db):
        svc = FlowService(test_db)
        svc.create("no-step")
        assert svc.get_step_content("no-step", "nonexistent") is None

    def test_get_flow_steps(self, test_db):
        svc = FlowService(test_db)
        svc.create("ordered", steps=[
            {"name": "b", "position": 1},
            {"name": "a", "position": 0},
            {"name": "c", "position": 2},
        ])
        steps = svc.get_flow_steps("ordered")
        assert steps == ["a", "b", "c"]

    def test_get_next_step(self, test_db):
        svc = FlowService(test_db)
        svc.create("next-test", steps=[
            {"name": "research", "position": 0},
            {"name": "execute", "position": 1},
            {"name": "summary", "position": 2},
        ])
        assert svc.get_next_step("next-test", "research") == "execute"
        assert svc.get_next_step("next-test", "execute") == "summary"
        assert svc.get_next_step("next-test", "summary") is None

    def test_duplicate(self, test_db):
        svc = FlowService(test_db)
        svc.create("source", description="Original", steps=[
            {"name": "step1", "position": 0, "content": "Content 1"},
        ])
        copy = svc.duplicate("source", "copy")
        assert copy.name == "copy"
        assert copy.description == "Original"
        assert len(copy.steps) == 1
        assert copy.steps[0].content == "Content 1"

    def test_seed_defaults(self, test_db):
        svc = FlowService(test_db)
        svc.seed_defaults()
        flow = svc.get_by_name("default")
        assert flow is not None
        assert len(flow.steps) == 3

    def test_seed_defaults_idempotent(self, test_db):
        svc = FlowService(test_db)
        svc.seed_defaults()
        svc.seed_defaults()
        flows = svc.list_all()
        defaults = [f for f in flows if f.name == "default"]
        assert len(defaults) == 1

    def test_export_import_round_trip(self, test_db):
        svc = FlowService(test_db)
        svc.create("export-test", description="For export", steps=[
            {"name": "step1", "position": 0, "content": "# Step 1"},
            {"name": "step2", "position": 1, "content": "# Step 2"},
        ])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        svc.export_flows(path)

        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "export-test"
        assert len(data["flows"][0]["steps"]) == 2

        for step in list(svc.get_by_name("export-test").steps):
            test_db.delete(step)
        test_db.delete(svc.get_by_name("export-test"))
        test_db.commit()

        count = svc.import_flows(path)
        assert count == 1
        reimported = svc.get_by_name("export-test")
        assert reimported is not None
        assert len(reimported.steps) == 2

        path.unlink()


    def test_create_flow_with_gates(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("gated-flow", steps=[
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

    def test_add_step_with_gates(self, test_db):
        svc = FlowService(test_db)
        flow = svc.create("add-gated")
        step = svc.add_step(
            flow.id, "test", "# Test",
            gates=[{"command": "npm test", "message": "Tests pass"}],
        )
        assert step.get_gates() == [{"command": "npm test", "message": "Tests pass"}]

    def test_get_step_obj(self, test_db):
        svc = FlowService(test_db)
        svc.create("obj-test", steps=[
            {"name": "step1", "position": 0, "content": "# Step 1"},
        ])
        step = svc.get_step_obj("obj-test", "step1")
        assert step is not None
        assert step.name == "step1"
        assert svc.get_step_obj("obj-test", "nonexistent") is None

    def test_step_content_excludes_gate_info(self, test_db):
        svc = FlowService(test_db)
        svc.create("gate-content", steps=[
            {
                "name": "build",
                "position": 0,
                "content": "# Build",
                "gates": [{"command": "make build", "message": "Build succeeds"}],
            },
        ])
        content = svc.get_step_content("gate-content", "build")
        assert "GATES" not in content
        assert "make build" not in content

    def test_duplicate_preserves_gates(self, test_db):
        svc = FlowService(test_db)
        svc.create("src-gates", steps=[
            {
                "name": "test",
                "position": 0,
                "content": "# Test",
                "gates": [{"command": "pytest", "message": "Tests pass"}],
            },
        ])
        copy = svc.duplicate("src-gates", "dst-gates")
        assert copy.steps[0].get_gates() == [{"command": "pytest", "message": "Tests pass"}]

    def test_export_import_gates_round_trip(self, test_db):
        svc = FlowService(test_db)
        gates = [{"command": "ls *.png", "message": "Screenshots exist"}]
        svc.create("gate-export", steps=[
            {"name": "test", "position": 0, "content": "# Test", "gates": gates},
        ])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        svc.export_flows(path)
        data = json.loads(path.read_text())
        exported_gates = data["flows"][0]["steps"][0].get("gates", [])
        assert exported_gates == gates

        for step in list(svc.get_by_name("gate-export").steps):
            test_db.delete(step)
        test_db.delete(svc.get_by_name("gate-export"))
        test_db.commit()

        svc.import_flows(path)
        reimported = svc.get_by_name("gate-export")
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
        variables = {"run.id": "abc123", "task.id": "t001", "flow.name": "react-js"}
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
    def test_enqueue(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Test")

        run = run_svc.enqueue(test_project.id, task.id, "default")
        assert run.flow_name == "default"
        assert run.started_at is None
        assert run.status == "queued"

    def test_get_pending(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Pending")
        run_svc.enqueue(test_project.id, task.id)

        pending = run_svc.get_pending(test_project.id)
        assert pending is not None
        assert pending.task_id == task.id

    def test_mark_started(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Start me")
        run = run_svc.enqueue(test_project.id, task.id)

        run_svc.mark_started(run.id)
        assert run.started_at is not None
        assert run.status == "running"

    def test_update_step(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Step test")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run_svc.update_step(task.id, "research")
        assert run.current_step == "research"
        completed = json.loads(run.steps_completed)
        assert "research" in completed

        run_svc.update_step(task.id, "execute")
        assert run.current_step == "execute"
        completed = json.loads(run.steps_completed)
        assert completed == ["research", "execute"]

    def test_set_log_path(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Log path test")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run_svc.set_log_path(run.id, "/tmp/wt/.llmflows/agent-abc123.log")
        assert run.log_path == "/tmp/wt/.llmflows/agent-abc123.log"

    def test_set_prompt(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Prompt test")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run_svc.set_prompt(run.id, "# Full agent prompt\nDo the task.")
        assert run.prompt == "# Full agent prompt\nDo the task."

    def test_set_summary(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Summary test")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run_svc.set_summary(task.id, "Did everything right.")
        assert run.summary == "Did everything right."
        assert run.outcome == "completed"

    def test_mark_completed(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Complete me")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run_svc.mark_completed(run.id, outcome="completed")
        assert run.completed_at is not None
        assert run.outcome == "completed"
        assert run.status == "completed"

    def test_mark_completed_failed(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Fail me")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run_svc.mark_completed(run.id, outcome="failed")
        assert run.outcome == "failed"

    def test_get_active(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Active test")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        active = run_svc.get_active(task.id)
        assert active is not None
        assert active.id == run.id

    def test_get_active_none_after_completion(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "No active")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)
        run_svc.mark_completed(run.id)

        assert run_svc.get_active(task.id) is None

    def test_get_history(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "History test")

        r1 = run_svc.enqueue(test_project.id, task.id, "default")
        run_svc.mark_started(r1.id)
        run_svc.set_summary(task.id, "First run summary")
        run_svc.mark_completed(r1.id)

        r2 = run_svc.enqueue(test_project.id, task.id, "custom")
        run_svc.mark_started(r2.id)
        run_svc.set_summary(task.id, "Second run summary")
        run_svc.mark_completed(r2.id)

        history = run_svc.get_history(task.id)
        assert len(history) == 2
        assert history[0].flow_name == "default"
        assert history[1].flow_name == "custom"

    def test_list_by_project(self, test_db, test_project):
        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        t1 = task_svc.create(test_project.id, "Task 1")
        t2 = task_svc.create(test_project.id, "Task 2")
        run_svc.enqueue(test_project.id, t1.id)
        run_svc.enqueue(test_project.id, t2.id)

        runs = run_svc.list_by_project(test_project.id)
        assert len(runs) == 2


class TestDaemonTimeout:
    def test_timeout_kills_expired_run(self, test_db, test_project):
        """Daemon should mark a run as 'timeout' when it exceeds run_timeout_minutes."""
        from llmflows.services.daemon import Daemon

        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Long task")
        task_svc.update(task.id, worktree_branch="task-branch")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run.started_at = datetime.now(timezone.utc) - timedelta(minutes=45)
        test_db.commit()

        daemon = Daemon.__new__(Daemon)
        daemon.run_timeout_minutes = 30

        with patch.object(AgentService, "is_agent_running", return_value=True), \
             patch.object(AgentService, "kill_agent", return_value=True) as mock_kill:
            daemon._process_project(test_project, task_svc, run_svc)
            mock_kill.assert_called_once_with(test_project.path, "task-branch")

        test_db.refresh(run)
        assert run.completed_at is not None
        assert run.outcome == "timeout"

    def test_no_timeout_when_within_limit(self, test_db, test_project):
        """Daemon should not kill a run that is still within the timeout."""
        from llmflows.services.daemon import Daemon

        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Short task")
        task_svc.update(task.id, worktree_branch="task-branch")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run.started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        test_db.commit()

        daemon = Daemon.__new__(Daemon)
        daemon.run_timeout_minutes = 30

        with patch.object(AgentService, "is_agent_running", return_value=True), \
             patch.object(AgentService, "kill_agent") as mock_kill:
            daemon._process_project(test_project, task_svc, run_svc)
            mock_kill.assert_not_called()

        test_db.refresh(run)
        assert run.completed_at is None

    def test_timeout_disabled_when_zero(self, test_db, test_project):
        """Setting run_timeout_minutes to 0 disables the timeout."""
        from llmflows.services.daemon import Daemon

        task_svc = TaskService(test_db)
        run_svc = RunService(test_db)
        task = task_svc.create(test_project.id, "Forever task")
        task_svc.update(task.id, worktree_branch="task-branch")
        run = run_svc.enqueue(test_project.id, task.id)
        run_svc.mark_started(run.id)

        run.started_at = datetime.now(timezone.utc) - timedelta(hours=5)
        test_db.commit()

        daemon = Daemon.__new__(Daemon)
        daemon.run_timeout_minutes = 0

        with patch.object(AgentService, "is_agent_running", return_value=True), \
             patch.object(AgentService, "kill_agent") as mock_kill:
            daemon._process_project(test_project, task_svc, run_svc)
            mock_kill.assert_not_called()

        test_db.refresh(run)
        assert run.completed_at is None
