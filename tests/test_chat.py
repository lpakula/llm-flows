"""Tests for the chat assistant service."""

import json
from unittest.mock import patch

from llmflows.services.chat import build_flow_context
from llmflows.services.flow import FlowService
from llmflows.services.run import RunService


def _flow_context(test_db, flow_name: str, space_id: str) -> str:
    with patch("llmflows.db.database.get_session", return_value=test_db), \
         patch.object(test_db, "close"):
        return build_flow_context(flow_name, space_id)


class TestBuildFlowContext:
    def test_includes_gate_failures_for_interrupted_run(self, test_db, test_space):
        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("chat-ctx", space_id=test_space.id, steps=[
            {"name": "build", "position": 0, "content": "# Build"},
        ])
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)

        sr = run_svc.create_step_run(run.id, "build", 0, flow.name)
        run_svc.mark_step_completed(sr.id, outcome="gate_failed")
        sr.gate_failures = json.dumps([
            {
                "command": "npm test",
                "message": "Tests must pass",
                "stderr": "1 failed",
            },
        ])
        run_svc.mark_completed(run.id, outcome="interrupted", summary="Gate failed after retries")
        test_db.commit()

        ctx = _flow_context(test_db, flow.name, test_space.id)

        assert "Failure details" in ctx
        assert "Tests must pass" in ctx
        assert "npm test" in ctx
        assert "1 failed" in ctx
        assert "interrupted" in ctx

    def test_includes_error_summary_without_gate_failures(self, test_db, test_space):
        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("chat-err", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)
        run_svc.mark_completed(run.id, outcome="error", summary="Runner container exited unexpectedly")
        test_db.commit()

        ctx = _flow_context(test_db, flow.name, test_space.id)

        assert "Failure details" in ctx
        assert "Runner container exited unexpectedly" in ctx

    def test_omits_failure_section_for_successful_runs(self, test_db, test_space):
        flow_svc = FlowService(test_db)
        run_svc = RunService(test_db)
        flow = flow_svc.create("chat-ok", space_id=test_space.id)
        run = run_svc.enqueue(test_space.id, flow.id)
        run_svc.mark_started(run.id)
        run_svc.mark_completed(run.id, outcome="completed")
        test_db.commit()

        ctx = _flow_context(test_db, flow.name, test_space.id)

        assert "Recent runs" in ctx
        assert "Failure details" not in ctx
