"""Flow service -- CRUD for flows and steps, seed defaults, export/import, snapshots."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import Flow, FlowStep

def _serialize_json_list(value) -> str:
    """Normalize a list (gates/ifs/skills) to a JSON string for storage."""
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _serialize_gates(gates) -> str:
    return _serialize_json_list(gates)


class FlowService:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        name: str,
        project_id: str,
        description: str = "",
        steps: Optional[list[dict]] = None,
    ) -> Flow:
        existing = self.get_by_name(name, project_id)
        if existing:
            raise ValueError(f"Flow '{name}' already exists in this project")

        flow = Flow(name=name, project_id=project_id, description=description)
        self.session.add(flow)
        self.session.flush()

        if steps:
            for i, step_data in enumerate(steps):
                step = FlowStep(
                    flow_id=flow.id,
                    name=step_data["name"],
                    position=step_data.get("position", i),
                    content=step_data.get("content", ""),
                    gates=_serialize_gates(step_data.get("gates")),
                    ifs=_serialize_json_list(step_data.get("ifs")),
                    agent_alias=step_data.get("agent_alias", "standard"),
                    step_type=step_data.get("step_type", "agent"),
                    allow_max=step_data.get("allow_max", False),
                    max_gate_retries=step_data.get("max_gate_retries", 5),
                    skills=_serialize_json_list(step_data.get("skills")),
                )
                self.session.add(step)

        self.session.commit()
        return flow

    def get(self, flow_id: str) -> Optional[Flow]:
        return self.session.query(Flow).filter_by(id=flow_id).first()

    def get_by_name(self, name: str, project_id: Optional[str] = None) -> Optional[Flow]:
        q = self.session.query(Flow).filter_by(name=name)
        if project_id:
            q = q.filter_by(project_id=project_id)
        return q.first()

    def has_human_steps(self, flow_name: str, project_id: Optional[str] = None) -> bool:
        """Return True if any step in the flow is a manual (human) step."""
        flow = self.get_by_name(flow_name, project_id)
        if not flow:
            return False
        return any(
            (s.step_type or "agent") == "manual"
            for s in flow.steps
        )

    def list_by_project(self, project_id: str) -> list[Flow]:
        return self.session.query(Flow).filter_by(project_id=project_id).order_by(Flow.name).all()

    def update(self, flow_id: str, **kwargs) -> Optional[Flow]:
        flow = self.get(flow_id)
        if not flow:
            return None
        for key, value in kwargs.items():
            if hasattr(flow, key) and key not in ("id", "created_at"):
                setattr(flow, key, value)
        flow.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        return flow

    def delete(self, flow_id: str) -> bool:
        flow = self.get(flow_id)
        if not flow:
            return False
        self.session.delete(flow)
        self.session.commit()
        return True

    def add_step(
        self, flow_id: str, name: str, content: str = "",
        position: Optional[int] = None, gates: Optional[list] = None,
        ifs: Optional[list] = None,
        agent_alias: str = "standard", step_type: str = "agent",
        allow_max: bool = False, max_gate_retries: int = 5,
        skills: Optional[list] = None,
    ) -> Optional[FlowStep]:
        flow = self.get(flow_id)
        if not flow:
            return None

        if position is None:
            max_pos = max((s.position for s in flow.steps), default=-1)
            position = max_pos + 1

        step = FlowStep(
            flow_id=flow_id, name=name, position=position,
            content=content, gates=_serialize_gates(gates),
            ifs=_serialize_json_list(ifs),
            agent_alias=agent_alias, step_type=step_type,
            allow_max=allow_max, max_gate_retries=max_gate_retries,
            skills=_serialize_json_list(skills),
        )
        self.session.add(step)
        flow.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        return step

    def update_step(self, step_id: str, **kwargs) -> Optional[FlowStep]:
        step = self.session.query(FlowStep).filter_by(id=step_id).first()
        if not step:
            return None
        for key, value in kwargs.items():
            if hasattr(step, key) and key not in ("id", "flow_id", "created_at"):
                setattr(step, key, value)
        step.updated_at = datetime.now(timezone.utc)
        flow = self.get(step.flow_id)
        if flow:
            flow.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        return step

    def remove_step(self, step_id: str) -> bool:
        step = self.session.query(FlowStep).filter_by(id=step_id).first()
        if not step:
            return False
        flow = self.get(step.flow_id)
        self.session.delete(step)
        if flow:
            flow.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        return True

    def reorder_steps(self, flow_id: str, step_ids: list[str]) -> bool:
        flow = self.get(flow_id)
        if not flow:
            return False
        step_map = {s.id: s for s in flow.steps}
        for i, sid in enumerate(step_ids):
            if sid in step_map:
                step_map[sid].position = i
        flow.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        return True

    def get_step_obj(self, flow_name: str, step_name: str, project_id: Optional[str] = None) -> Optional[FlowStep]:
        flow = self.get_by_name(flow_name, project_id)
        if not flow:
            return None
        for step in flow.steps:
            if step.name == step_name:
                return step
        return None

    def get_flow_steps(self, flow_name: str, project_id: Optional[str] = None) -> list[str]:
        flow = self.get_by_name(flow_name, project_id)
        if not flow:
            return []
        return [s.name for s in sorted(flow.steps, key=lambda s: s.position)]

    def get_next_step(self, flow_name: str, current: str, project_id: Optional[str] = None) -> Optional[str]:
        steps = self.get_flow_steps(flow_name, project_id)
        try:
            idx = steps.index(current)
            return steps[idx + 1] if idx + 1 < len(steps) else None
        except ValueError:
            return None

    def duplicate(self, source_name: str, new_name: str, project_id: Optional[str] = None) -> Optional[Flow]:
        source = self.get_by_name(source_name, project_id)
        if not source:
            return None

        steps_data = [
            {"name": s.name, "position": s.position, "content": s.content,
             "gates": s.get_gates(), "ifs": s.get_ifs(),
             "agent_alias": s.agent_alias or "standard",
             "step_type": s.step_type or "agent",
             "allow_max": bool(s.allow_max),
             "max_gate_retries": s.max_gate_retries if s.max_gate_retries is not None else 5,
             "skills": s.get_skills()}
            for s in sorted(source.steps, key=lambda s: s.position)
        ]
        return self.create(
            name=new_name,
            project_id=source.project_id,
            description=source.description,
            steps=steps_data,
        )

    def build_flow_snapshot(self, flow_name: str, project_id: Optional[str] = None) -> Optional[dict]:
        """Return a plain-dict snapshot of a flow (stored as JSON on FlowRun.flow_snapshot)."""
        source = self.get_by_name(flow_name, project_id)
        if not source:
            return None
        return {
            "id": source.id,
            "name": source.name,
            "description": source.description or "",
            "steps": [
                {
                    "name": s.name,
                    "position": s.position,
                    "content": s.content or "",
                    "gates": s.get_gates(),
                    "ifs": s.get_ifs(),
                    "agent_alias": s.agent_alias or "standard",
                    "step_type": s.step_type or "agent",
                    "allow_max": bool(s.allow_max),
                    "max_gate_retries": s.max_gate_retries if s.max_gate_retries is not None else 5,
                    "skills": s.get_skills(),
                }
                for s in sorted(source.steps, key=lambda s: s.position)
            ],
        }

    def export_flows(self, project_id: str, path: Optional[Path] = None) -> dict:
        """Export all flows for a project to a dict (optionally write to file)."""
        flows = self.list_by_project(project_id)
        data = {
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "flows": [],
        }
        for flow in flows:
            flow_data = {
                "name": flow.name,
                "description": flow.description,
                "steps": [],
            }
            for s in sorted(flow.steps, key=lambda s: s.position):
                step_data = {"name": s.name, "position": s.position, "content": s.content}
                gates = s.get_gates()
                if gates:
                    step_data["gates"] = gates
                ifs = s.get_ifs()
                if ifs:
                    step_data["ifs"] = ifs
                if s.agent_alias and s.agent_alias != "standard":
                    step_data["agent_alias"] = s.agent_alias
                if s.step_type and s.step_type != "agent":
                    step_data["step_type"] = s.step_type
                if s.allow_max:
                    step_data["allow_max"] = True
                if s.max_gate_retries is not None and s.max_gate_retries != 5:
                    step_data["max_gate_retries"] = s.max_gate_retries
                skills = s.get_skills()
                if skills:
                    step_data["skills"] = skills
                flow_data["steps"].append(step_data)
            data["flows"].append(flow_data)

        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(data, indent=2))

        return data

    def import_flows(self, path: Path, project_id: str) -> int:
        """Import flows from a JSON file. Upserts by name. Returns count imported."""
        data = json.loads(Path(path).read_text())
        return self._import_flows_data(data, project_id=project_id, skip_existing=False)

    def _import_flows_data(self, data: dict, project_id: str, skip_existing: bool = False) -> int:
        """Import flows from parsed JSON data."""
        count = 0
        for flow_data in data.get("flows", []):
            name = flow_data["name"]
            existing = self.get_by_name(name, project_id)

            if existing and skip_existing:
                continue

            if existing:
                for step in list(existing.steps):
                    self.session.delete(step)
                existing.description = flow_data.get("description", "")
                existing.updated_at = datetime.now(timezone.utc)
                self.session.flush()

                for i, step_data in enumerate(flow_data.get("steps", [])):
                    step = FlowStep(
                        flow_id=existing.id,
                        name=step_data["name"],
                        position=step_data.get("position", i),
                        content=step_data.get("content", ""),
                        gates=_serialize_gates(step_data.get("gates")),
                        ifs=_serialize_json_list(step_data.get("ifs")),
                        agent_alias=step_data.get("agent_alias", "standard"),
                        step_type=step_data.get("step_type", "agent"),
                        allow_max=step_data.get("allow_max", False),
                        max_gate_retries=step_data.get("max_gate_retries", 5),
                        skills=_serialize_json_list(step_data.get("skills")),
                    )
                    self.session.add(step)
            else:
                self.create(
                    name=name,
                    project_id=project_id,
                    description=flow_data.get("description", ""),
                    steps=flow_data.get("steps", []),
                )
            count += 1

        self.session.commit()
        return count
