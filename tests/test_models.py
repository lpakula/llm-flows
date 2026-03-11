"""Tests for database models."""

from llmflows.db.models import (
    Base,
    Flow,
    FlowStep,
    Project,
    Task,
    TaskRun,
    TaskType,
    generate_id,
)


def test_generate_id():
    id1 = generate_id()
    id2 = generate_id()
    assert len(id1) == 6
    assert id1 != id2
    assert id1.isalnum()



def test_task_type_values():
    assert TaskType.FEATURE.value == "feature"
    assert TaskType.FIX.value == "fix"
    assert TaskType.REFACTOR.value == "refactor"
    assert TaskType.CHORE.value == "chore"


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


def test_create_task(test_db, test_project):
    task = Task(
        project_id=test_project.id,
        name="Test task",
        description="A test task",
        type=TaskType.FEATURE,
    )
    test_db.add(task)
    test_db.commit()

    fetched = test_db.query(Task).first()
    assert fetched.name == "Test task"
    assert fetched.project_id == test_project.id


def test_task_to_dict(test_db, test_project):
    task = Task(
        project_id=test_project.id,
        name="Dict test",
        type=TaskType.FIX,
    )
    test_db.add(task)
    test_db.commit()

    d = task.to_dict()
    assert d["name"] == "Dict test"
    assert d["type"] == "fix"
    assert "status" not in d


def test_project_task_cascade(test_db, test_project):
    task = Task(project_id=test_project.id, name="Cascade test")
    test_db.add(task)
    test_db.commit()

    test_db.delete(test_project)
    test_db.commit()

    assert test_db.query(Task).count() == 0


class TestFlowModel:
    def test_create_flow(self, test_db):
        flow = Flow(name="test-flow", description="A test flow")
        test_db.add(flow)
        test_db.commit()

        fetched = test_db.query(Flow).first()
        assert fetched.name == "test-flow"
        assert fetched.description == "A test flow"
        assert len(fetched.id) == 6

    def test_flow_to_dict(self, test_db):
        flow = Flow(name="dict-flow", description="A test flow")
        test_db.add(flow)
        test_db.commit()

        d = flow.to_dict()
        assert d["name"] == "dict-flow"
        assert d["description"] == "A test flow"
        assert "steps" in d
        assert d["steps"] == []

    def test_flow_step_relationship(self, test_db):
        flow = Flow(name="with-steps")
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

    def test_flow_cascade_deletes_steps(self, test_db):
        flow = Flow(name="cascade-flow")
        test_db.add(flow)
        test_db.flush()

        step = FlowStep(flow_id=flow.id, name="step1", position=0)
        test_db.add(step)
        test_db.commit()

        test_db.delete(flow)
        test_db.commit()

        assert test_db.query(FlowStep).count() == 0

    def test_flow_name_unique(self, test_db):
        import pytest
        from sqlalchemy.exc import IntegrityError

        f1 = Flow(name="unique-flow")
        test_db.add(f1)
        test_db.commit()

        f2 = Flow(name="unique-flow")
        test_db.add(f2)
        with pytest.raises(IntegrityError):
            test_db.commit()


class TestFlowStepModel:
    def test_create_step(self, test_db):
        flow = Flow(name="step-test")
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

    def test_step_to_dict(self, test_db):
        flow = Flow(name="step-dict")
        test_db.add(flow)
        test_db.flush()

        step = FlowStep(flow_id=flow.id, name="execute", position=1, content="# Execute")
        test_db.add(step)
        test_db.commit()

        d = step.to_dict()
        assert d["name"] == "execute"
        assert d["position"] == 1
        assert d["content"] == "# Execute"


class TestTaskRunModel:
    def test_create_task_run(self, test_db, test_project):
        task = Task(project_id=test_project.id, name="run-test")
        test_db.add(task)
        test_db.flush()

        run = TaskRun(
            project_id=test_project.id,
            task_id=task.id,
            flow_name="default",
        )
        test_db.add(run)
        test_db.commit()

        fetched = test_db.query(TaskRun).first()
        assert fetched.flow_name == "default"
        assert fetched.outcome is None
        assert fetched.started_at is None
        assert fetched.completed_at is None

    def test_task_run_to_dict(self, test_db, test_project):
        task = Task(project_id=test_project.id, name="dict-run")
        test_db.add(task)
        test_db.flush()

        run = TaskRun(
            project_id=test_project.id,
            task_id=task.id,
            flow_name="custom",
            current_step="research",
            log_path="/tmp/wt/.llmflows/agent-abc123.log",
            prompt="# Test prompt\nDo the thing.",
        )
        test_db.add(run)
        test_db.commit()

        d = run.to_dict()
        assert d["flow_name"] == "custom"
        assert d["current_step"] == "research"
        assert d["outcome"] is None
        assert d["log_path"] == "/tmp/wt/.llmflows/agent-abc123.log"
        assert d["prompt"] == "# Test prompt\nDo the thing."

    def test_task_run_cascade_on_task_delete(self, test_db, test_project):
        task = Task(project_id=test_project.id, name="cascade-run")
        test_db.add(task)
        test_db.flush()

        run = TaskRun(project_id=test_project.id, task_id=task.id, flow_name="default")
        test_db.add(run)
        test_db.commit()

        test_db.delete(task)
        test_db.commit()

        assert test_db.query(TaskRun).count() == 0

    def test_task_runs_relationship(self, test_db, test_project):
        task = Task(project_id=test_project.id, name="runs-rel")
        test_db.add(task)
        test_db.flush()

        r1 = TaskRun(project_id=test_project.id, task_id=task.id, flow_name="default")
        r2 = TaskRun(project_id=test_project.id, task_id=task.id, flow_name="custom")
        test_db.add_all([r1, r2])
        test_db.commit()

        assert len(task.runs) == 2
