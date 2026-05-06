"""Optimizer service — analyses step run history to recommend cheaper model tiers."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import FlowStep, StepQualityRating, StepRun


QUALITY_THRESHOLD = 0.80
MIN_RATED_RUNS = 2

MODEL_TIER_ORDER = ["mini", "normal", "max"]

TIER_KEYWORDS: dict[str, list[str]] = {
    "mini": ["mini", "fast", "haiku", "flash", "nano", "lite", "small"],
    "normal": ["normal", "sonnet", "pro", "medium"],
    "max": ["max", "opus", "o1", "large"],
}


def _classify_tier(alias: str, model: str) -> str:
    alias_lower = alias.lower()
    model_lower = model.lower()
    for tier, keywords in TIER_KEYWORDS.items():
        for kw in keywords:
            if kw in alias_lower or kw in model_lower:
                return tier
    return "normal"


def _tier_rank(tier: str) -> int:
    try:
        return MODEL_TIER_ORDER.index(tier)
    except ValueError:
        return 1


class OptimizerService:
    def __init__(self, session: Session):
        self.session = session

    def rate_step_run(
        self, step_run_id: str, rating: int, flow_id: str | None = None,
    ) -> StepQualityRating:
        """Record a quality rating for a step run. rating: 1 (good) or -1 (bad)."""
        rating = 1 if rating >= 0 else -1
        sr = self.session.query(StepRun).filter_by(id=step_run_id).first()
        if not sr:
            raise ValueError(f"StepRun {step_run_id} not found")

        resolved_flow_id = flow_id
        if not resolved_flow_id:
            from ..db.models import FlowRun
            run = self.session.query(FlowRun).filter_by(id=sr.flow_run_id).first()
            resolved_flow_id = run.flow_id if run else ""

        existing = (
            self.session.query(StepQualityRating)
            .filter_by(step_run_id=step_run_id)
            .first()
        )
        if existing:
            existing.rating = rating
            self.session.commit()
            return existing

        rec = StepQualityRating(
            step_run_id=step_run_id,
            flow_id=resolved_flow_id or "",
            step_name=sr.step_name,
            model=sr.model or "",
            agent_alias="",
            rating=rating,
        )
        self.session.add(rec)
        self.session.commit()
        return rec

    def get_rating(self, step_run_id: str) -> Optional[StepQualityRating]:
        return (
            self.session.query(StepQualityRating)
            .filter_by(step_run_id=step_run_id)
            .first()
        )

    def get_recommendations(self, flow_id: str) -> list[dict]:
        """Analyse quality ratings for a flow and return per-step optimization hints.

        A step is recommended for downgrade when its ratings on the current tier
        show a high enough approval rate (>= QUALITY_THRESHOLD) and there are
        enough samples (>= MIN_RATED_RUNS).
        """
        ratings = (
            self.session.query(StepQualityRating)
            .filter_by(flow_id=flow_id)
            .all()
        )
        if not ratings:
            return []

        steps = (
            self.session.query(FlowStep)
            .filter_by(flow_id=flow_id)
            .all()
        )
        step_alias_map = {s.name: s.agent_alias or "normal" for s in steps}

        by_step: dict[str, list[StepQualityRating]] = defaultdict(list)
        for r in ratings:
            by_step[r.step_name].append(r)

        results: list[dict] = []
        for step_name, step_ratings in by_step.items():
            current_alias = step_alias_map.get(step_name, "normal")
            current_tier = _classify_tier(current_alias, "")

            if current_tier == "mini":
                continue

            total = len(step_ratings)
            if total < MIN_RATED_RUNS:
                continue

            positive = sum(1 for r in step_ratings if r.rating > 0)
            quality_score = positive / total

            if quality_score >= QUALITY_THRESHOLD:
                target_tier_idx = max(0, _tier_rank(current_tier) - 1)
                target_tier = MODEL_TIER_ORDER[target_tier_idx]
                if target_tier == current_tier:
                    continue

                results.append({
                    "step_name": step_name,
                    "current_tier": current_tier,
                    "recommended_tier": target_tier,
                    "quality_score": round(quality_score, 2),
                    "rated_runs": total,
                    "positive_runs": positive,
                    "confidence": "high" if total >= 5 else "medium",
                })

        return results
