"""Flow service -- CRUD for flows and steps, seed defaults, export/import."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import case
from sqlalchemy.orm import Session

from ..db.models import Flow, FlowStep
from ..defaults import get_defaults_dir


def _serialize_json_list(value) -> str:
    """Normalize a list (gates/ifs) to a JSON string for storage."""
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
        description: str = "",
        steps: Optional[list[dict]] = None,
    ) -> Flow:
        existing = self.get_by_name(name)
        if existing:
            raise ValueError(f"Flow '{name}' already exists")

        flow = Flow(name=name, description=description)
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
                )
                self.session.add(step)

        self.session.commit()
        return flow

    def get(self, flow_id: str) -> Optional[Flow]:
        return self.session.query(Flow).filter_by(id=flow_id).first()

    def get_by_name(self, name: str) -> Optional[Flow]:
        return self.session.query(Flow).filter_by(name=name).first()

    def list_all(self) -> list[Flow]:
        return self.session.query(Flow).order_by(
            case((Flow.name == "default", 0), else_=1),
            Flow.name,
        ).all()

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
        if flow.name == "default":
            raise ValueError("Cannot delete the default flow")
        self.session.delete(flow)
        self.session.commit()
        return True

    def add_step(
        self, flow_id: str, name: str, content: str = "",
        position: Optional[int] = None, gates: Optional[list] = None,
        ifs: Optional[list] = None,
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

    def get_step_obj(self, flow_name: str, step_name: str) -> Optional[FlowStep]:
        flow = self.get_by_name(flow_name)
        if not flow:
            return None
        for step in flow.steps:
            if step.name == step_name:
                return step
        return None

    def get_flow_steps(self, flow_name: str) -> list[str]:
        flow = self.get_by_name(flow_name)
        if not flow:
            return []
        return [s.name for s in sorted(flow.steps, key=lambda s: s.position)]

    def get_next_step(self, flow_name: str, current: str) -> Optional[str]:
        steps = self.get_flow_steps(flow_name)
        try:
            idx = steps.index(current)
            return steps[idx + 1] if idx + 1 < len(steps) else None
        except ValueError:
            return None

    def duplicate(self, source_name: str, new_name: str) -> Optional[Flow]:
        source = self.get_by_name(source_name)
        if not source:
            return None

        steps_data = [
            {"name": s.name, "position": s.position, "content": s.content,
             "gates": s.get_gates(), "ifs": s.get_ifs()}
            for s in sorted(source.steps, key=lambda s: s.position)
        ]
        return self.create(
            name=new_name,
            description=source.description,
            steps=steps_data,
        )

    def seed_defaults(self) -> None:
        """Seed default flows from defaults/flows.json. Idempotent -- skips existing."""
        flows_file = get_defaults_dir() / "flows.json"
        if not flows_file.exists():
            return
        data = json.loads(flows_file.read_text())
        self._import_flows_data(data, skip_existing=True)

    def export_flows(self, path: Optional[Path] = None) -> dict:
        """Export all flows to a dict (optionally write to file)."""
        flows = self.list_all()
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
                flow_data["steps"].append(step_data)
            data["flows"].append(flow_data)

        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(data, indent=2))

        return data

    def import_flows(self, path: Path) -> int:
        """Import flows from a JSON file. Upserts by name. Returns count imported."""
        data = json.loads(Path(path).read_text())
        return self._import_flows_data(data, skip_existing=False)

    def _import_flows_data(self, data: dict, skip_existing: bool = False) -> int:
        """Import flows from parsed JSON data."""
        count = 0
        for flow_data in data.get("flows", []):
            name = flow_data["name"]
            existing = self.get_by_name(name)

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
                    )
                    self.session.add(step)
            else:
                self.create(
                    name=name,
                    description=flow_data.get("description", ""),
                    steps=flow_data.get("steps", []),
                )
            count += 1

        self.session.commit()
        return count
