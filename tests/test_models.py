"""Tests for database models."""

from datetime import datetime, timedelta, timezone

from llmflows.db.models import (
    Base,
    Flow,
    FlowRun,
    FlowStep,
    Space,
    StepRun,
    generate_id,
)


def test_generate_id():
    id1 = generate_id()
    id2 = generate_id()
    assert len(id1) == 6
    assert id1 != id2
    assert id1.isalnum()


def test_create_space(test_db):
    space = Space(name="my-space", path="/tmp/my-space")
    test_db.add(space)
    test_db.commit()

    fetched = test_db.query(Space).first()
    assert fetched.name == "my-space"
    assert fetched.path == "/tmp/my-space"
    assert len(fetched.id) == 6
    assert fetched.created_at is not None


def test_space_to_dict(test_db):
    space = Space(name="test", path="/tmp/test")
    test_db.add(space)
    test_db.commit()

    d = space.to_dict()
    assert d["name"] == "test"
    assert d["path"] == "/tmp/test"
    assert "id" in d
    assert "created_at" in d


class TestFlowModel:
    def test_create_flow(self, test_db, test_space):
        flow = Flow(name="test-flow", description="A test flow", space_id=test_space.id)
        test_db.add(flow)
        test_db.commit()

        fetched = test_db.query(Flow).first()
        assert fetched.name == "test-flow"
        assert fetched.description == "A test flow"
        assert len(fetched.id) == 6

    def test_flow_to_dict(self, test_db, test_space):
        flow = Flow(name="dict-flow", description="A test flow", space_id=test_space.id)
        test_db.add(flow)
        test_db.commit()

        d = flow.to_dict()
        assert d["name"] == "dict-flow"
        assert d["description"] == "A test flow"
        assert "steps" in d
        assert d["steps"] == []

    def test_flow_step_relationship(self, test_db, test_space):
        flow = Flow(name="with-steps", space_id=test_space.id)
        test_db.add(flow)
        test_db.flush()

        step1 = FlowStep(flow_id=flow.id, name="research", position=0, content="# Research")
        step2 = FlowStep(flow_id=flow.id, name="execute", position=1, content="# Execute")
        test_db.add_all([step1, step2])
        test_db.commit()

        fetched = test_db.query(Flow).first()
        assert len(fetched.steps) == 2
        assert fetched.steps[0].name == "research"
        assert fetched.steps[1].name == "execute"

    def test_flow_cascade_deletes_steps(self, test_db, test_space):
        flow = Flow(name="cascade-flow", space_id=test_space.id)
        test_db.add(flow)
        test_db.flush()

        step = FlowStep(flow_id=flow.id, name="step1", position=0)
        test_db.add(step)
        test_db.commit()

        test_db.delete(flow)
        test_db.commit()

        assert test_db.query(FlowStep).count() == 0

    def test_flow_name_unique(self, test_db, test_space):
        import pytest
        from sqlalchemy.exc import IntegrityError

        f1 = Flow(name="unique-flow", space_id=test_space.id)
        test_db.add(f1)
        test_db.commit()

        f2 = Flow(name="unique-flow", space_id=test_space.id)
        test_db.add(f2)
        with pytest.raises(IntegrityError):
            test_db.commit()


class TestFlowStepModel:
    def test_create_step(self, test_db, test_space):
        flow = Flow(name="step-test", space_id=test_space.id)
        test_db.add(flow)
        test_db.flush()

        step = FlowStep(
            flow_id=flow.id,
            name="research",
            position=0,
            content="# Research\nDo the research.",
        )
        test_db.add(step)
        test_db.commit()

        fetched = test_db.query(FlowStep).first()
        assert fetched.name == "research"
        assert fetched.position == 0
        assert "Research" in fetched.content

    def test_step_to_dict(self, test_db, test_space):
        flow = Flow(name="step-dict", space_id=test_space.id)
        test_db.add(flow)
        test_db.flush()

        step = FlowStep(flow_id=flow.id, name="execute", position=1, content="# Execute")
        test_db.add(step)
        test_db.commit()

        d = step.to_dict()
        assert d["name"] == "execute"
        assert d["position"] == 1
        assert d["content"] == "# Execute"


class TestFlowRunModel:
    def test_create_flow_run(self, test_db, test_space):
        flow = Flow(name="run-flow", space_id=test_space.id)
        test_db.add(flow)
        test_db.flush()

        run = FlowRun(
            space_id=test_space.id,
            flow_id=flow.id,
        )
        test_db.add(run)
        test_db.commit()

        fetched = test_db.query(FlowRun).first()
        assert fetched.flow_id == flow.id
        assert fetched.outcome is None
        assert fetched.started_at is None
        assert fetched.completed_at is None

    def test_flow_run_to_dict(self, test_db, test_space):
        flow = Flow(name="dict-run-flow", space_id=test_space.id)
        test_db.add(flow)
        test_db.flush()

        run = FlowRun(
            space_id=test_space.id,
            flow_id=flow.id,
            current_step="research",
            log_path="/tmp/wt/.llmflows/agent-abc123.log",
            prompt="# Test prompt\nDo the thing.",
        )
        test_db.add(run)
        test_db.commit()

        d = run.to_dict()
        assert d["flow_name"] == "dict-run-flow"
        assert d["current_step"] == "research"
        assert d["outcome"] is None
        assert d["log_path"] == "/tmp/wt/.llmflows/agent-abc123.log"
        assert d["prompt"] == "# Test prompt\nDo the thing."

    def test_flow_run_cascade_on_space_delete(self, test_db, test_space):
        run = FlowRun(space_id=test_space.id)
        test_db.add(run)
        test_db.commit()

        test_db.delete(test_space)
        test_db.commit()

        assert test_db.query(FlowRun).count() == 0

    def test_flow_runs_relationship(self, test_db, test_space):
        r1 = FlowRun(space_id=test_space.id)
        r2 = FlowRun(space_id=test_space.id)
        test_db.add_all([r1, r2])
        test_db.commit()

        assert len(test_space.flow_runs) == 2

    def test_recovery_count_defaults_to_zero(self, test_db, test_space):
        run = FlowRun(space_id=test_space.id)
        test_db.add(run)
        test_db.commit()

        assert run.recovery_count == 0

    def test_recovery_count_in_to_dict(self, test_db, test_space):
        run = FlowRun(space_id=test_space.id)
        test_db.add(run)
        test_db.commit()

        d = run.to_dict()
        assert "recovery_count" in d
        assert d["recovery_count"] == 0

    def test_status_returns_interrupted_when_outcome_is_interrupted(self, test_db, test_space):
        from datetime import datetime, timezone

        run = FlowRun(space_id=test_space.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = "interrupted"
        test_db.add(run)
        test_db.commit()

        assert run.status == "interrupted"

    def test_status_returns_timeout_when_outcome_is_timeout(self, test_db, test_space):
        from datetime import datetime, timezone

        run = FlowRun(space_id=test_space.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = "timeout"
        test_db.add(run)
        test_db.commit()

        assert run.status == "timeout"

    def test_status_returns_error_when_outcome_is_error(self, test_db, test_space):
        from datetime import datetime, timezone

        run = FlowRun(space_id=test_space.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = "error"
        test_db.add(run)
        test_db.commit()

        assert run.status == "error"

    def test_status_returns_completed_for_successful_outcome(self, test_db, test_space):
        from datetime import datetime, timezone

        run = FlowRun(space_id=test_space.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = "completed"
        test_db.add(run)
        test_db.commit()

        assert run.status == "completed"

    def test_status_returns_completed_when_outcome_is_none(self, test_db, test_space):
        from datetime import datetime, timezone

        run = FlowRun(space_id=test_space.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = None
        test_db.add(run)
        test_db.commit()

        assert run.status == "completed"


class TestStepRunDuration:
    """Tests for StepRun.duration_seconds, especially HITL exclusion."""

    def _make_run(self, test_db, test_space):
        flow = Flow(name="dur-flow", space_id=test_space.id)
        test_db.add(flow)
        test_db.flush()
        run = FlowRun(space_id=test_space.id, flow_id=flow.id)
        run.started_at = datetime.now(timezone.utc)
        test_db.add(run)
        test_db.commit()
        return run

    def test_agent_step_duration_uses_completed_at(self, test_db, test_space):
        run = self._make_run(test_db, test_space)
        now = datetime.now(timezone.utc)
        sr = StepRun(
            flow_run_id=run.id, step_name="agent-step",
            step_position=0, flow_name="dur-flow",
            started_at=now - timedelta(minutes=10),
            completed_at=now,
        )
        test_db.add(sr)
        test_db.commit()
        assert abs(sr.duration_seconds - 600) < 1

    def test_hitl_step_duration_excludes_wait_time(self, test_db, test_space):
        """HITL step that ran for 2 min then awaited user for 12 hours."""
        run = self._make_run(test_db, test_space)
        now = datetime.now(timezone.utc)
        sr = StepRun(
            flow_run_id=run.id, step_name="hitl-step",
            step_position=0, flow_name="dur-flow",
            started_at=now - timedelta(hours=12, minutes=2),
            awaiting_user_at=now - timedelta(hours=12),
            completed_at=now,
        )
        test_db.add(sr)
        test_db.commit()
        assert abs(sr.duration_seconds - 120) < 1

    def test_hitl_step_still_awaiting(self, test_db, test_space):
        """HITL step currently awaiting user — duration is only agent time."""
        run = self._make_run(test_db, test_space)
        now = datetime.now(timezone.utc)
        sr = StepRun(
            flow_run_id=run.id, step_name="hitl-waiting",
            step_position=0, flow_name="dur-flow",
            started_at=now - timedelta(hours=8, minutes=5),
            awaiting_user_at=now - timedelta(hours=8),
        )
        test_db.add(sr)
        test_db.commit()
        assert abs(sr.duration_seconds - 300) < 1

    def test_flow_run_duration_excludes_hitl_wait(self, test_db, test_space):
        """FlowRun.duration_seconds should sum step durations, excluding HITL wait."""
        run = self._make_run(test_db, test_space)
        now = datetime.now(timezone.utc)
        hitl = StepRun(
            flow_run_id=run.id, step_name="hitl",
            step_position=0, flow_name="dur-flow",
            started_at=now - timedelta(hours=12, minutes=3),
            awaiting_user_at=now - timedelta(hours=12),
            completed_at=now - timedelta(minutes=10),
        )
        agent = StepRun(
            flow_run_id=run.id, step_name="implement",
            step_position=1, flow_name="dur-flow",
            started_at=now - timedelta(minutes=10),
            completed_at=now,
        )
        test_db.add_all([hitl, agent])
        test_db.commit()
        test_db.refresh(run)
        total = run.duration_seconds
        assert total is not None
        assert abs(total - (180 + 600)) < 2
