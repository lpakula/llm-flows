"""Tests for database models."""

from llmflows.db.models import (
    Base,
    Flow,
    FlowRun,
    FlowStep,
    Project,
    generate_id,
)


def test_generate_id():
    id1 = generate_id()
    id2 = generate_id()
    assert len(id1) == 6
    assert id1 != id2
    assert id1.isalnum()


def test_create_project(test_db):
    project = Project(name="my-project", path="/tmp/my-project")
    test_db.add(project)
    test_db.commit()

    fetched = test_db.query(Project).first()
    assert fetched.name == "my-project"
    assert fetched.path == "/tmp/my-project"
    assert len(fetched.id) == 6
    assert fetched.created_at is not None


def test_project_to_dict(test_db):
    project = Project(name="test", path="/tmp/test")
    test_db.add(project)
    test_db.commit()

    d = project.to_dict()
    assert d["name"] == "test"
    assert d["path"] == "/tmp/test"
    assert "id" in d
    assert "created_at" in d


class TestFlowModel:
    def test_create_flow(self, test_db, test_project):
        flow = Flow(name="test-flow", description="A test flow", project_id=test_project.id)
        test_db.add(flow)
        test_db.commit()

        fetched = test_db.query(Flow).first()
        assert fetched.name == "test-flow"
        assert fetched.description == "A test flow"
        assert len(fetched.id) == 6

    def test_flow_to_dict(self, test_db, test_project):
        flow = Flow(name="dict-flow", description="A test flow", project_id=test_project.id)
        test_db.add(flow)
        test_db.commit()

        d = flow.to_dict()
        assert d["name"] == "dict-flow"
        assert d["description"] == "A test flow"
        assert "steps" in d
        assert d["steps"] == []

    def test_flow_step_relationship(self, test_db, test_project):
        flow = Flow(name="with-steps", project_id=test_project.id)
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

    def test_flow_cascade_deletes_steps(self, test_db, test_project):
        flow = Flow(name="cascade-flow", project_id=test_project.id)
        test_db.add(flow)
        test_db.flush()

        step = FlowStep(flow_id=flow.id, name="step1", position=0)
        test_db.add(step)
        test_db.commit()

        test_db.delete(flow)
        test_db.commit()

        assert test_db.query(FlowStep).count() == 0

    def test_flow_name_unique(self, test_db, test_project):
        import pytest
        from sqlalchemy.exc import IntegrityError

        f1 = Flow(name="unique-flow", project_id=test_project.id)
        test_db.add(f1)
        test_db.commit()

        f2 = Flow(name="unique-flow", project_id=test_project.id)
        test_db.add(f2)
        with pytest.raises(IntegrityError):
            test_db.commit()


class TestFlowStepModel:
    def test_create_step(self, test_db, test_project):
        flow = Flow(name="step-test", project_id=test_project.id)
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

    def test_step_to_dict(self, test_db, test_project):
        flow = Flow(name="step-dict", project_id=test_project.id)
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
    def test_create_flow_run(self, test_db, test_project):
        flow = Flow(name="run-flow", project_id=test_project.id)
        test_db.add(flow)
        test_db.flush()

        run = FlowRun(
            project_id=test_project.id,
            flow_id=flow.id,
        )
        test_db.add(run)
        test_db.commit()

        fetched = test_db.query(FlowRun).first()
        assert fetched.flow_id == flow.id
        assert fetched.outcome is None
        assert fetched.started_at is None
        assert fetched.completed_at is None

    def test_flow_run_to_dict(self, test_db, test_project):
        flow = Flow(name="dict-run-flow", project_id=test_project.id)
        test_db.add(flow)
        test_db.flush()

        run = FlowRun(
            project_id=test_project.id,
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

    def test_flow_run_cascade_on_project_delete(self, test_db, test_project):
        run = FlowRun(project_id=test_project.id)
        test_db.add(run)
        test_db.commit()

        test_db.delete(test_project)
        test_db.commit()

        assert test_db.query(FlowRun).count() == 0

    def test_flow_runs_relationship(self, test_db, test_project):
        r1 = FlowRun(project_id=test_project.id)
        r2 = FlowRun(project_id=test_project.id)
        test_db.add_all([r1, r2])
        test_db.commit()

        assert len(test_project.flow_runs) == 2

    def test_recovery_count_defaults_to_zero(self, test_db, test_project):
        run = FlowRun(project_id=test_project.id)
        test_db.add(run)
        test_db.commit()

        assert run.recovery_count == 0

    def test_recovery_count_in_to_dict(self, test_db, test_project):
        run = FlowRun(project_id=test_project.id)
        test_db.add(run)
        test_db.commit()

        d = run.to_dict()
        assert "recovery_count" in d
        assert d["recovery_count"] == 0

    def test_status_returns_interrupted_when_outcome_is_interrupted(self, test_db, test_project):
        from datetime import datetime, timezone

        run = FlowRun(project_id=test_project.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = "interrupted"
        test_db.add(run)
        test_db.commit()

        assert run.status == "interrupted"

    def test_status_returns_timeout_when_outcome_is_timeout(self, test_db, test_project):
        from datetime import datetime, timezone

        run = FlowRun(project_id=test_project.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = "timeout"
        test_db.add(run)
        test_db.commit()

        assert run.status == "timeout"

    def test_status_returns_error_when_outcome_is_error(self, test_db, test_project):
        from datetime import datetime, timezone

        run = FlowRun(project_id=test_project.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = "error"
        test_db.add(run)
        test_db.commit()

        assert run.status == "error"

    def test_status_returns_completed_for_successful_outcome(self, test_db, test_project):
        from datetime import datetime, timezone

        run = FlowRun(project_id=test_project.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = "completed"
        test_db.add(run)
        test_db.commit()

        assert run.status == "completed"

    def test_status_returns_completed_when_outcome_is_none(self, test_db, test_project):
        from datetime import datetime, timezone

        run = FlowRun(project_id=test_project.id)
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.outcome = None
        test_db.add(run)
        test_db.commit()

        assert run.status == "completed"

