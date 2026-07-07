"""Tests for the FastAPI REST API."""

import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llmflows.db.models import AgentAlias, Base, Flow, FlowStep, Space
from llmflows.services.audit import AuditResult, FlowAuditService
from llmflows.services.flow import FlowService
from llmflows.services.space import SpaceService
from llmflows.ui.server import app


@pytest.fixture
def api_db(tmp_path):
    """Set up a shared in-memory DB and patch the server to use it."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    space_path = str(tmp_path / "test-space")
    (tmp_path / "test-space").mkdir()

    setup_session = Session()
    space = Space(name="test-space", path=space_path)
    setup_session.add(space)
    setup_session.flush()

    flow = Flow(name="default", description="Default flow", space_id=space.id)
    setup_session.add(flow)
    setup_session.flush()
    step = FlowStep(flow_id=flow.id, name="research", position=0, content="# Research")
    setup_session.add(step)
    alias = AgentAlias(name="normal", type="pi", agent="pi", model="default")
    setup_session.add(alias)
    setup_session.commit()

    FlowAuditService.save_audit(space_path, "default", AuditResult(status="safe", summary="Test fixture"))

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


class TestStopRunAPI:
    def test_stop_run_kills_container(self, client, api_db):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, patch

        run = MagicMock()
        run.id = "abc123"
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = None

        with patch("llmflows.ui.server.RunService") as MockRunSvc:
            mock_run_svc = MockRunSvc.return_value
            mock_run_svc.get.return_value = run
            mock_run_svc.cancel_run.return_value = (run, True)
            response = client.post("/api/runs/abc123/stop")

        assert response.status_code == 200
        assert response.json()["killed"] is True
        mock_run_svc.cancel_run.assert_called_once_with("abc123")

    def test_stop_run_kills_host_agent_when_no_container(self, client, api_db):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, patch

        run = MagicMock()
        run.id = "abc123"
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = None

        with patch("llmflows.ui.server.RunService") as MockRunSvc:
            mock_run_svc = MockRunSvc.return_value
            mock_run_svc.get.return_value = run
            mock_run_svc.cancel_run.return_value = (run, True)
            response = client.post("/api/runs/abc123/stop")

        assert response.status_code == 200
        assert response.json()["killed"] is True
        mock_run_svc.cancel_run.assert_called_once_with("abc123")


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


class TestDaemonConfigAPI:
    def test_get_daemon_config(self, client, api_db):
        config = {"daemon": {"poll_interval_seconds": 10, "keep_awake": False}}
        with patch("llmflows.ui.server.load_system_config", return_value=config):
            response = client.get("/api/config/daemon")
        assert response.status_code == 200
        data = response.json()
        assert data["poll_interval_seconds"] == 10
        assert data["keep_awake"] is False

    def test_update_daemon_config_keep_awake(self, client, api_db):
        stored = {"daemon": {"keep_awake": False}}
        with (
            patch("llmflows.ui.server.load_system_config", return_value=stored),
            patch("llmflows.ui.server.save_system_config") as mock_save,
        ):
            response = client.patch(
                "/api/config/daemon",
                json={"keep_awake": True},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["keep_awake"] is True
        mock_save.assert_called_once()


class TestGatewayAPI:
    def test_get_gateway_config(self, client, api_db):
        with patch("llmflows.ui.server.load_system_config", return_value={}):
            response = client.get("/api/config/gateway")
        assert response.status_code == 200
        data = response.json()
        assert data["telegram_enabled"] is False
        assert data["telegram_bot_token"] == ""
        assert data["telegram_allowed_chat_ids"] == []

    def test_get_gateway_config_with_channels(self, client, api_db):
        config = {
            "channels": {
                "telegram": {"enabled": True, "bot_token": "tok123", "allowed_chat_ids": [111]},
            }
        }
        with patch("llmflows.ui.server.load_system_config", return_value=config):
            response = client.get("/api/config/gateway")
        assert response.status_code == 200
        data = response.json()
        assert data["telegram_enabled"] is True
        assert data["telegram_bot_token"] == "tok123"
        assert data["telegram_allowed_chat_ids"] == [111]

    def test_update_gateway_config_telegram(self, client, api_db):
        stored = {}
        with (
            patch("llmflows.ui.server.load_system_config", return_value=stored),
            patch("llmflows.ui.server.save_system_config") as mock_save,
            patch("llmflows.ui.server._signal_gateway_restart"),
        ):
            response = client.patch(
                "/api/config/gateway",
                json={"telegram_enabled": True, "telegram_bot_token": "new-tok"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["telegram_enabled"] is True
        assert data["telegram_bot_token"] == "new-tok"
        mock_save.assert_called_once()

    def test_update_gateway_partial(self, client, api_db):
        stored = {
            "channels": {
                "telegram": {"enabled": True, "bot_token": "old-tok", "allowed_chat_ids": [1, 2]},
            }
        }
        with (
            patch("llmflows.ui.server.load_system_config", return_value=stored),
            patch("llmflows.ui.server.save_system_config"),
            patch("llmflows.ui.server._signal_gateway_restart"),
        ):
            response = client.patch(
                "/api/config/gateway",
                json={"telegram_allowed_chat_ids": [1, 2, 3]},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["telegram_enabled"] is True
        assert data["telegram_bot_token"] == "old-tok"
        assert data["telegram_allowed_chat_ids"] == [1, 2, 3]


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


class TestFlowImportAudit:
    """Tests for pre-import security audit enforcement (issue #25)."""

    def _make_client_with_audit(self, tmp_path, audit_enabled=True):
        """Set up a DB, space with audit toggle, and return (client, space_id)."""
        import io
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        space_path = str(tmp_path / "audit-space")
        (tmp_path / "audit-space").mkdir()

        session = Session()
        space = Space(
            name="audit-space",
            path=space_path,
            audit_flows_on_import=audit_enabled,
        )
        session.add(space)
        session.flush()
        alias = AgentAlias(name="normal", type="pi", agent="pi", model="default")
        session.add(alias)
        session.commit()
        space_id = space.id
        session.close()

        def mock_services():
            s = Session()
            return s, SpaceService(s)

        return Session, space_id, space_path, mock_services

    def test_import_rejected_when_unsafe(self, tmp_path):
        import io, json
        Session, space_id, space_path, mock_svc = self._make_client_with_audit(tmp_path, audit_enabled=True)

        unsafe_result = AuditResult(status="unsafe", summary="Dangerous patterns found", findings=["rm -rf /"])
        payload = json.dumps({"flows": [{"name": "bad-flow", "steps": [{"name": "s1", "position": 0}]}]})

        with (
            patch("llmflows.ui.server._get_services", mock_svc),
            patch("llmflows.services.audit.FlowAuditService.run_audit", return_value=unsafe_result) as mock_audit,
        ):
            c = TestClient(app)
            resp = c.post(
                f"/api/spaces/{space_id}/flows/import",
                files={"file": ("f.json", io.BytesIO(payload.encode()), "application/json")},
            )
        assert resp.status_code == 422
        assert "bad-flow" in resp.json()["detail"]
        mock_audit.assert_called_once()

        session = Session()
        assert session.query(Flow).filter_by(name="bad-flow").first() is None
        session.close()

    def test_import_succeeds_when_safe(self, tmp_path):
        import io, json
        Session, space_id, space_path, mock_svc = self._make_client_with_audit(tmp_path, audit_enabled=True)

        safe_result = AuditResult(status="safe", summary="All clear")
        payload = json.dumps({"flows": [{"name": "good-flow", "version": 1, "steps": [{"name": "s1", "position": 0}]}]})

        with (
            patch("llmflows.ui.server._get_services", mock_svc),
            patch("llmflows.services.audit.FlowAuditService.run_audit", return_value=safe_result),
            patch("llmflows.services.audit.FlowAuditService.save_audit") as mock_save,
        ):
            c = TestClient(app)
            resp = c.post(
                f"/api/spaces/{space_id}/flows/import",
                files={"file": ("f.json", io.BytesIO(payload.encode()), "application/json")},
            )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 1
        mock_save.assert_called_once_with(space_path, "good-flow", safe_result)

    def test_import_skips_audit_when_disabled(self, tmp_path):
        import io, json
        Session, space_id, space_path, mock_svc = self._make_client_with_audit(tmp_path, audit_enabled=False)

        payload = json.dumps({"flows": [{"name": "any-flow", "version": 1, "steps": [{"name": "s1", "position": 0}]}]})

        with (
            patch("llmflows.ui.server._get_services", mock_svc),
            patch("llmflows.services.audit.FlowAuditService.run_audit") as mock_audit,
        ):
            c = TestClient(app)
            resp = c.post(
                f"/api/spaces/{space_id}/flows/import",
                files={"file": ("f.json", io.BytesIO(payload.encode()), "application/json")},
            )
        assert resp.status_code == 200
        mock_audit.assert_not_called()

    def test_import_rejects_all_when_one_unsafe(self, tmp_path):
        import io, json
        Session, space_id, space_path, mock_svc = self._make_client_with_audit(tmp_path, audit_enabled=True)

        safe_result = AuditResult(status="safe", summary="OK")
        unsafe_result = AuditResult(status="unsafe", summary="Bad stuff", findings=["exfiltration"])

        def side_effect(path, name, flow_dict):
            return unsafe_result if name == "evil-flow" else safe_result

        payload = json.dumps({"flows": [
            {"name": "nice-flow", "steps": [{"name": "s1", "position": 0}]},
            {"name": "evil-flow", "steps": [{"name": "s1", "position": 0}]},
        ]})

        with (
            patch("llmflows.ui.server._get_services", mock_svc),
            patch("llmflows.services.audit.FlowAuditService.run_audit", side_effect=side_effect),
        ):
            c = TestClient(app)
            resp = c.post(
                f"/api/spaces/{space_id}/flows/import",
                files={"file": ("f.json", io.BytesIO(payload.encode()), "application/json")},
            )
        assert resp.status_code == 422
        assert "evil-flow" in resp.json()["detail"]

        session = Session()
        assert session.query(Flow).filter_by(name="nice-flow").first() is None
        assert session.query(Flow).filter_by(name="evil-flow").first() is None
        session.close()


class TestInboxMuteAPI:
    def test_get_inbox_muted_default(self, client):
        with patch("llmflows.ui.server.load_system_config", return_value={"daemon": {}}):
            response = client.get("/api/inbox/muted")
            assert response.status_code == 200
            assert response.json()["muted"] is False

    def test_get_inbox_muted_true(self, client):
        with patch("llmflows.ui.server.load_system_config", return_value={"daemon": {"inbox_muted": True}}):
            response = client.get("/api/inbox/muted")
            assert response.status_code == 200
            assert response.json()["muted"] is True

    def test_set_inbox_muted(self, client):
        saved = {}
        def mock_save(config):
            saved["config"] = config

        with patch("llmflows.ui.server.load_system_config", return_value={"daemon": {}}), \
             patch("llmflows.ui.server.save_system_config", mock_save):
            response = client.post("/api/inbox/muted", json={"muted": True})
            assert response.status_code == 200
            assert response.json()["muted"] is True
            assert saved["config"]["daemon"]["inbox_muted"] is True

    def test_set_inbox_unmuted(self, client):
        saved = {}
        def mock_save(config):
            saved["config"] = config

        with patch("llmflows.ui.server.load_system_config", return_value={"daemon": {"inbox_muted": True}}), \
             patch("llmflows.ui.server.save_system_config", mock_save):
            response = client.post("/api/inbox/muted", json={"muted": False})
            assert response.status_code == 200
            assert response.json()["muted"] is False
            assert saved["config"]["daemon"]["inbox_muted"] is False
