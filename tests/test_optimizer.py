"""Tests for the optimizer service (quality ratings + recommendations)."""

import pytest

from llmflows.db.models import Flow, FlowStep, FlowRun, StepRun, StepQualityRating
from llmflows.services.optimizer import OptimizerService, _classify_tier
from llmflows.services.run import RunService
from llmflows.services.space import SpaceService


@pytest.fixture
def optimizer_env(test_db):
    """Set up a space, flow, and some step runs for optimizer tests."""
    space_svc = SpaceService(test_db)
    space = space_svc.register("opt-test", "/tmp/opt-test")

    flow = Flow(space_id=space.id, name="test-flow")
    test_db.add(flow)
    test_db.commit()

    step1 = FlowStep(flow_id=flow.id, name="Research", position=0, agent_alias="normal")
    step2 = FlowStep(flow_id=flow.id, name="Implement", position=1, agent_alias="max")
    test_db.add_all([step1, step2])
    test_db.commit()

    run = FlowRun(space_id=space.id, flow_id=flow.id)
    test_db.add(run)
    test_db.commit()

    sr1 = StepRun(
        flow_run_id=run.id, step_name="Research", step_position=0,
        flow_name="test-flow", model="claude-sonnet",
    )
    sr2 = StepRun(
        flow_run_id=run.id, step_name="Implement", step_position=1,
        flow_name="test-flow", model="claude-opus",
    )
    test_db.add_all([sr1, sr2])
    test_db.commit()

    return {
        "session": test_db,
        "space": space,
        "flow": flow,
        "run": run,
        "step_runs": [sr1, sr2],
    }


class TestClassifyTier:
    def test_mini_keywords(self):
        assert _classify_tier("mini", "") == "mini"
        assert _classify_tier("", "claude-haiku") == "mini"
        assert _classify_tier("fast", "") == "mini"

    def test_normal_keywords(self):
        assert _classify_tier("normal", "") == "normal"
        assert _classify_tier("", "claude-sonnet") == "normal"

    def test_max_keywords(self):
        assert _classify_tier("max", "") == "max"
        assert _classify_tier("", "claude-opus") == "max"

    def test_unknown_defaults_normal(self):
        assert _classify_tier("custom-alias", "unknown-model") == "normal"


class TestRateStepRun:
    def test_rate_positive(self, optimizer_env):
        svc = OptimizerService(optimizer_env["session"])
        sr = optimizer_env["step_runs"][0]
        rating = svc.rate_step_run(sr.id, 1)
        assert rating.rating == 1
        assert rating.step_name == "Research"
        assert rating.flow_id == optimizer_env["flow"].id

    def test_rate_negative(self, optimizer_env):
        svc = OptimizerService(optimizer_env["session"])
        sr = optimizer_env["step_runs"][0]
        rating = svc.rate_step_run(sr.id, -1)
        assert rating.rating == -1

    def test_rate_updates_existing(self, optimizer_env):
        svc = OptimizerService(optimizer_env["session"])
        sr = optimizer_env["step_runs"][0]
        svc.rate_step_run(sr.id, 1)
        updated = svc.rate_step_run(sr.id, -1)
        assert updated.rating == -1

        all_ratings = optimizer_env["session"].query(StepQualityRating).all()
        assert len(all_ratings) == 1

    def test_rate_nonexistent_step_run(self, optimizer_env):
        svc = OptimizerService(optimizer_env["session"])
        with pytest.raises(ValueError, match="not found"):
            svc.rate_step_run("zzzzzz", 1)


class TestGetRating:
    def test_no_rating(self, optimizer_env):
        svc = OptimizerService(optimizer_env["session"])
        assert svc.get_rating(optimizer_env["step_runs"][0].id) is None

    def test_after_rating(self, optimizer_env):
        svc = OptimizerService(optimizer_env["session"])
        sr = optimizer_env["step_runs"][0]
        svc.rate_step_run(sr.id, 1)
        rating = svc.get_rating(sr.id)
        assert rating is not None
        assert rating.rating == 1


class TestGetRecommendations:
    def _add_rated_runs(self, session, flow, step_name, model, count, positive_count):
        """Helper to create multiple step runs with ratings."""
        from llmflows.db.models import FlowRun
        for i in range(count):
            run = FlowRun(space_id=flow.space_id, flow_id=flow.id)
            session.add(run)
            session.flush()

            sr = StepRun(
                flow_run_id=run.id, step_name=step_name, step_position=0,
                flow_name=flow.name, model=model,
            )
            session.add(sr)
            session.flush()

            rating_val = 1 if i < positive_count else -1
            r = StepQualityRating(
                step_run_id=sr.id, flow_id=flow.id,
                step_name=step_name, model=model, rating=rating_val,
            )
            session.add(r)
        session.commit()

    def test_no_ratings_returns_empty(self, optimizer_env):
        svc = OptimizerService(optimizer_env["session"])
        assert svc.get_recommendations(optimizer_env["flow"].id) == []

    def test_insufficient_ratings(self, optimizer_env):
        svc = OptimizerService(optimizer_env["session"])
        sr = optimizer_env["step_runs"][1]
        svc.rate_step_run(sr.id, 1)
        recs = svc.get_recommendations(optimizer_env["flow"].id)
        assert len(recs) == 0

    def test_recommends_downgrade_for_high_quality(self, optimizer_env):
        session = optimizer_env["session"]
        flow = optimizer_env["flow"]
        self._add_rated_runs(session, flow, "Implement", "claude-opus", 5, 5)

        svc = OptimizerService(session)
        recs = svc.get_recommendations(flow.id)
        assert len(recs) == 1
        assert recs[0]["step_name"] == "Implement"
        assert recs[0]["current_tier"] == "max"
        assert recs[0]["recommended_tier"] == "normal"
        assert recs[0]["quality_score"] == 1.0

    def test_no_recommendation_for_low_quality(self, optimizer_env):
        session = optimizer_env["session"]
        flow = optimizer_env["flow"]
        self._add_rated_runs(session, flow, "Implement", "claude-opus", 5, 2)

        svc = OptimizerService(session)
        recs = svc.get_recommendations(flow.id)
        assert len(recs) == 0

    def test_no_recommendation_for_mini_tier(self, optimizer_env):
        session = optimizer_env["session"]
        flow = optimizer_env["flow"]
        step = session.query(FlowStep).filter_by(name="Research").first()
        step.agent_alias = "mini"
        session.commit()

        self._add_rated_runs(session, flow, "Research", "claude-haiku", 5, 5)

        svc = OptimizerService(session)
        recs = svc.get_recommendations(flow.id)
        step_names = [r["step_name"] for r in recs]
        assert "Research" not in step_names

    def test_confidence_levels(self, optimizer_env):
        session = optimizer_env["session"]
        flow = optimizer_env["flow"]

        self._add_rated_runs(session, flow, "Implement", "claude-opus", 3, 3)

        svc = OptimizerService(session)
        recs = svc.get_recommendations(flow.id)
        assert len(recs) == 1
        assert recs[0]["confidence"] == "medium"

        self._add_rated_runs(session, flow, "Implement", "claude-opus", 3, 3)

        recs = svc.get_recommendations(flow.id)
        rec = recs[0]
        assert rec["confidence"] == "high"
