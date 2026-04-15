"""Tests for the FastAPI REST API."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llmflows.db.models import Base, Flow, FlowStep, Project
from llmflows.services.flow import FlowService
from llmflows.services.project import ProjectService
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
    project = Project(name="test-project", path="/tmp/test-project")
    setup_session.add(project)
    setup_session.flush()

    flow = Flow(name="default", description="Default flow", project_id=project.id)
    setup_session.add(flow)
    setup_session.flush()
    step = FlowStep(flow_id=flow.id, name="research", position=0, content="# Research")
    setup_session.add(step)
    setup_session.commit()

    project_id = project.id
    flow_id = flow.id
    setup_session.close()

    def mock_get_services():
        s = Session()
        return s, ProjectService(s)

    with patch("llmflows.ui.server._get_services", mock_get_services):
        yield {"project_id": project_id, "flow_id": flow_id}

    Base.metadata.drop_all(engine)


@pytest.fixture
def client(api_db):
    return TestClient(app)


class TestProjectsAPI:
    def test_list_projects(self, client, api_db):
        response = client.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-project"

    def test_get_project(self, client, api_db):
        response = client.get(f"/api/projects/{api_db['project_id']}")
        assert response.status_code == 200
        assert response.json()["name"] == "test-project"

    def test_get_project_not_found(self, client):
        response = client.get("/api/projects/nope")
        assert response.status_code == 404


class TestFlowsAPI:
    def test_list_flows(self, client, api_db):
        pid = api_db["project_id"]
        response = client.get(f"/api/projects/{pid}/flows")
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
        assert "project" in data[0]
        assert "run_counts" in data[0]


class TestScheduleAPI:
    def test_schedule_flow_run(self, client, api_db):
        pid = api_db["project_id"]
        fid = api_db["flow_id"]
        response = client.post(
            f"/api/projects/{pid}/schedule",
            json={"flow_id": fid, "one_shot": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["flow_id"] == fid
        assert data["project_id"] == pid

    def test_schedule_flow_not_found(self, client, api_db):
        pid = api_db["project_id"]
        response = client.post(
            f"/api/projects/{pid}/schedule",
            json={"flow_id": "nope", "one_shot": False},
        )
        assert response.status_code == 404
