"""Tests for the FastAPI REST API."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llmflows.db.models import AgentAlias, Base, Flow, FlowStep, Space
from llmflows.services.flow import FlowService
from llmflows.services.space import SpaceService
from llmflows.ui.server import app


@pytest.fixture
def api_db():
    """Set up a shared in-memory DB and patch the server to use it."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    setup_session = Session()
    space = Space(name="test-space", path="/tmp/test-space")
    setup_session.add(space)
    setup_session.flush()

    flow = Flow(name="default", description="Default flow", space_id=space.id)
    setup_session.add(flow)
    setup_session.flush()
    step = FlowStep(flow_id=flow.id, name="research", position=0, content="# Research")
    setup_session.add(step)
    alias = AgentAlias(name="normal", type="pi", agent="cursor", model="default")
    setup_session.add(alias)
    setup_session.commit()

    space_id = space.id
    flow_id = flow.id
    setup_session.close()

    def mock_get_services():
        s = Session()
        return s, SpaceService(s)

    with patch("llmflows.ui.server._get_services", mock_get_services):
        yield {"space_id": space_id, "flow_id": flow_id}

    Base.metadata.drop_all(engine)


@pytest.fixture
def client(api_db):
    return TestClient(app)


class TestSpacesAPI:
    def test_list_spaces(self, client, api_db):
        response = client.get("/api/spaces")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-space"

    def test_get_space(self, client, api_db):
        response = client.get(f"/api/spaces/{api_db['space_id']}")
        assert response.status_code == 200
        assert response.json()["name"] == "test-space"

    def test_get_space_not_found(self, client):
        response = client.get("/api/spaces/nope")
        assert response.status_code == 404


class TestFlowsAPI:
    def test_list_flows(self, client, api_db):
        sid = api_db["space_id"]
        response = client.get(f"/api/spaces/{sid}/flows")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        names = [f["name"] for f in data]
        assert "default" in names

    def test_get_flow(self, client, api_db):
        flow_id = api_db["flow_id"]
        response = client.get(f"/api/flows/{flow_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "default"
        assert len(data["steps"]) == 1

    def test_get_flow_not_found(self, client):
        response = client.get("/api/flows/nope")
        assert response.status_code == 404


class TestDashboardAPI:
    def test_dashboard(self, client, api_db):
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert "space" in data[0]
        assert "run_counts" in data[0]


class TestScheduleAPI:
    def test_schedule_flow_run(self, client, api_db):
        sid = api_db["space_id"]
        fid = api_db["flow_id"]
        response = client.post(
            f"/api/spaces/{sid}/schedule",
            json={"flow_id": fid},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["flow_id"] == fid
        assert data["space_id"] == sid

    def test_schedule_flow_not_found(self, client, api_db):
        sid = api_db["space_id"]
        response = client.post(
            f"/api/spaces/{sid}/schedule",
            json={"flow_id": "nope"},
        )
        assert response.status_code == 404


class TestFlowVersioningAPI:
    def test_list_versions_empty(self, client, api_db):
        fid = api_db["flow_id"]
        response = client.get(f"/api/flows/{fid}/versions")
        assert response.status_code == 200
        assert response.json() == []

    def test_rollback_not_found(self, client, api_db):
        fid = api_db["flow_id"]
        response = client.post(f"/api/flows/{fid}/rollback/nonexistent")
        assert response.status_code == 404

    def test_list_versions_not_found(self, client):
        response = client.get("/api/flows/nope/versions")
        assert response.status_code == 404

    def test_get_version_not_found(self, client, api_db):
        fid = api_db["flow_id"]
        response = client.get(f"/api/flows/{fid}/versions/nope")
        assert response.status_code == 404

    def test_flow_includes_version(self, client, api_db):
        fid = api_db["flow_id"]
        response = client.get(f"/api/flows/{fid}")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert data["version"] >= 1

    def test_import_rejects_same_version(self, client, api_db):
        import io
        sid = api_db["space_id"]
        import json
        data = json.dumps({
            "flows": [{
                "name": "default",
                "version": 1,
                "steps": [{"name": "step1", "position": 0}],
            }]
        })
        response = client.post(
            f"/api/spaces/{sid}/flows/import",
            files={"file": ("flows.json", io.BytesIO(data.encode()), "application/json")},
        )
        assert response.status_code == 400
        assert "version" in response.json()["detail"].lower()

    def test_import_accepts_higher_version(self, client, api_db):
        import io
        sid = api_db["space_id"]
        import json
        data = json.dumps({
            "flows": [{
                "name": "default",
                "version": 2,
                "steps": [{"name": "step1", "position": 0, "content": "updated"}],
            }]
        })
        response = client.post(
            f"/api/spaces/{sid}/flows/import",
            files={"file": ("flows.json", io.BytesIO(data.encode()), "application/json")},
        )
        assert response.status_code == 200
        assert response.json()["imported"] == 1

    def test_approve_improvement_not_found(self, client, api_db):
        response = client.post("/api/inbox/nonexistent/improvement/approve")
        assert response.status_code == 404


class TestFlowMemoryAPI:
    def test_get_memory_empty(self, client, api_db):
        fid = api_db["flow_id"]
        response = client.get(f"/api/flows/{fid}/memory")
        assert response.status_code == 200
        assert response.json()["files"] == []

    def test_get_memory_not_found(self, client):
        response = client.get("/api/flows/nope/memory")
        assert response.status_code == 404

    def test_clear_memory_empty(self, client, api_db):
        fid = api_db["flow_id"]
        response = client.delete(f"/api/flows/{fid}/memory")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_delete_memory_file_not_found(self, client, api_db):
        fid = api_db["flow_id"]
        response = client.delete(f"/api/flows/{fid}/memory/nonexistent.md")
        assert response.status_code == 404

    def test_reject_improvement_not_found(self, client):
        response = client.post(
            "/api/inbox/nonexistent/improvement/reject",
            json={"reason": "not useful"},
        )
        assert response.status_code == 404

    def test_reject_improvement_saves_memory(self, client, api_db):
        import json
        import tempfile
        from pathlib import Path
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from unittest.mock import patch

        from llmflows.db.models import Base, Space, Flow, FlowStep, FlowRun, InboxItem
        from llmflows.services.space import SpaceService

        with tempfile.TemporaryDirectory() as tmpdir:
            space_path = Path(tmpdir) / "test-space"
            space_path.mkdir()

            engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()

            space = Space(name="test-space", path=str(space_path))
            session.add(space)
            session.flush()

            flow = Flow(name="my-flow", description="test", space_id=space.id)
            session.add(flow)
            session.flush()
            step = FlowStep(flow_id=flow.id, name="step1", position=0, content="# Step")
            session.add(step)
            session.flush()

            from datetime import datetime, timezone
            run = FlowRun(space_id=space.id, flow_id=flow.id, completed_at=datetime.now(timezone.utc), outcome="completed")
            session.add(run)
            session.flush()

            from llmflows.services.context import ContextService
            artifacts_dir = ContextService.get_artifacts_dir(space_path, run.id, run.flow_name)
            artifacts_dir.mkdir(parents=True)
            (artifacts_dir / "improvement.md").write_text("Add retry logic to step 1.")
            (artifacts_dir / "flow.json").write_text(json.dumps({
                "steps": [{"name": "step1", "position": 0}],
            }))

            inbox = InboxItem(type="flow_improvement", reference_id=run.id, space_id=space.id, title="Proposal")
            session.add(inbox)
            session.commit()
            inbox_id = inbox.id

            def mock_services():
                s = Session()
                return s, SpaceService(s)

            with patch("llmflows.ui.server._get_services", mock_services):
                from fastapi.testclient import TestClient
                from llmflows.ui.server import app
                c = TestClient(app)

                response = c.post(
                    f"/api/inbox/{inbox_id}/improvement/reject",
                    json={"reason": "I prefer manual retries"},
                )
                assert response.status_code == 200
                assert response.json()["ok"] is True

                flow_dir = ContextService.get_flow_dir(space_path, "my-flow")
                files = ContextService.list_memory_files(flow_dir)
                assert len(files) == 1
                assert files[0]["name"] == "rejected-proposals.md"
                assert "Add retry logic" in files[0]["content"]
                assert "I prefer manual retries" in files[0]["content"]
                assert "Rejected proposal" in files[0]["content"]

            session.close()
            Base.metadata.drop_all(engine)
