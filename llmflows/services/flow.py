"""Flow service -- CRUD for flows and steps, seed defaults, export/import, snapshots, validation."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import Flow, FlowStep

VALID_STEP_TYPES = ("agent", "code", "hitl")


def _normalize_step_type(value: str | None) -> str:
    """Normalize step type. Known explicit types pass through; anything else
    (including None, empty string, or unknown values) becomes 'agent'.
    'default' is accepted as a legacy alias for 'agent'."""
    if not value or value == "default":
        return "agent"
    return value if value in VALID_STEP_TYPES else "agent"


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
        space_id: str,
        description: str = "",
        steps: Optional[list[dict]] = None,
        requirements: Optional[dict] = None,
        variables: Optional[dict] = None,
    ) -> Flow:
        existing = self.get_by_name(name, space_id)
        if existing:
            raise ValueError(f"Flow '{name}' already exists in this space")

        flow = Flow(name=name, space_id=space_id, description=description)
        if requirements:
            flow.requirements = json.dumps(requirements)
        if variables:
            normalized = {}
            for k, v in variables.items():
                normalized[k] = v if isinstance(v, dict) else {"value": str(v) if v else "", "is_env": False}
            flow.variables = json.dumps(normalized)
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
                    agent_alias=step_data.get("agent_alias", "normal"),
                    step_type=_normalize_step_type(step_data.get("step_type")),
                    allow_max=step_data.get("allow_max", False),
                    max_gate_retries=step_data.get("max_gate_retries", 5),
                    skills=_serialize_json_list(step_data.get("skills")),
                    connectors=_serialize_json_list(step_data.get("connectors")),
                )
                self.session.add(step)

        self.session.commit()
        return flow

    def get(self, flow_id: str) -> Optional[Flow]:
        return self.session.query(Flow).filter_by(id=flow_id).first()

    def get_by_name(self, name: str, space_id: Optional[str] = None) -> Optional[Flow]:
        q = self.session.query(Flow).filter_by(name=name)
        if space_id:
            q = q.filter_by(space_id=space_id)
        return q.first()

    def has_human_steps(self, flow_name: str, space_id: Optional[str] = None) -> bool:
        """Return True if any step in the flow is a hitl (human-in-the-loop) step."""
        flow = self.get_by_name(flow_name, space_id)
        if not flow:
            return False
        return any(
            _normalize_step_type(s.step_type) == "hitl"
            for s in flow.steps
        )

    def list_by_space(self, space_id: str) -> list[Flow]:
        return self.session.query(Flow).filter_by(space_id=space_id).order_by(Flow.name).all()

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
        agent_alias: str = "normal", step_type: str = "agent",
        allow_max: bool = False, max_gate_retries: int = 5,
        skills: Optional[list] = None,
        connectors: Optional[list] = None,
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
            agent_alias=agent_alias,
            step_type=_normalize_step_type(step_type),
            allow_max=allow_max, max_gate_retries=max_gate_retries,
            skills=_serialize_json_list(skills),
            connectors=_serialize_json_list(connectors),
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

    def get_step_obj(self, flow_name: str, step_name: str, space_id: Optional[str] = None) -> Optional[FlowStep]:
        flow = self.get_by_name(flow_name, space_id)
        if not flow:
            return None
        for step in flow.steps:
            if step.name == step_name:
                return step
        return None

    def get_flow_steps(self, flow_name: str, space_id: Optional[str] = None) -> list[str]:
        flow = self.get_by_name(flow_name, space_id)
        if not flow:
            return []
        return [s.name for s in sorted(flow.steps, key=lambda s: s.position)]

    def get_next_step(self, flow_name: str, current: str, space_id: Optional[str] = None) -> Optional[str]:
        steps = self.get_flow_steps(flow_name, space_id)
        try:
            idx = steps.index(current)
            return steps[idx + 1] if idx + 1 < len(steps) else None
        except ValueError:
            return None

    def duplicate(self, source_name: str, new_name: str, space_id: Optional[str] = None) -> Optional[Flow]:
        source = self.get_by_name(source_name, space_id)
        if not source:
            return None

        steps_data = [
            {"name": s.name, "position": s.position, "content": s.content,
             "gates": s.get_gates(), "ifs": s.get_ifs(),
             "agent_alias": s.agent_alias or "normal",
             "step_type": _normalize_step_type(s.step_type),
             "allow_max": bool(s.allow_max),
             "max_gate_retries": s.max_gate_retries if s.max_gate_retries is not None else 5,
             "skills": s.get_skills(),
             "connectors": s.get_connectors()}
            for s in sorted(source.steps, key=lambda s: s.position)
        ]
        return self.create(
            name=new_name,
            space_id=source.space_id,
            description=source.description,
            steps=steps_data,
            requirements=source.get_requirements(),
        )

    def build_flow_snapshot(self, flow_name: str, space_id: Optional[str] = None) -> Optional[dict]:
        """Return a plain-dict snapshot of a flow (stored as JSON on FlowRun.flow_snapshot)."""
        source = self.get_by_name(flow_name, space_id)
        if not source:
            return None
        return {
            "id": source.id,
            "name": source.name,
            "description": source.description or "",
            "requirements": source.get_requirements(),
            "variables": source.get_variables(),
            "steps": [
                {
                    "name": s.name,
                    "position": s.position,
                    "content": s.content or "",
                    "gates": s.get_gates(),
                    "ifs": s.get_ifs(),
                    "agent_alias": s.agent_alias or "normal",
                    "step_type": _normalize_step_type(s.step_type),
                    "allow_max": bool(s.allow_max),
                    "max_gate_retries": s.max_gate_retries if s.max_gate_retries is not None else 5,
                    "skills": s.get_skills(),
                    "connectors": s.get_connectors(),
                }
                for s in sorted(source.steps, key=lambda s: s.position)
            ],
        }

    def export_flow_to_disk(self, flow_id: str, space_path: str) -> str:
        """Export a single flow as JSON to <space_path>/flows/<flow_name>.json.

        Returns the written file path.
        """
        flow = self.get(flow_id)
        if not flow:
            raise ValueError(f"Flow {flow_id} not found")

        flow_data: dict = {
            "name": flow.name,
            "description": flow.description,
            "steps": [],
        }
        reqs = flow.get_requirements()
        if reqs.get("connectors"):
            flow_data["requirements"] = reqs
        flow_variables = flow.get_variables()
        if flow_variables:
            flow_data["variables"] = flow_variables
        if flow.schedule_cron:
            flow_data["schedule_cron"] = flow.schedule_cron
            flow_data["schedule_timezone"] = flow.schedule_timezone or "UTC"
            flow_data["schedule_enabled"] = bool(flow.schedule_enabled)
        if flow.max_spend_usd:
            flow_data["max_spend_usd"] = flow.max_spend_usd
        if flow.max_concurrent_runs and flow.max_concurrent_runs != 1:
            flow_data["max_concurrent_runs"] = flow.max_concurrent_runs

        for s in sorted(flow.steps, key=lambda s: s.position):
            step_data: dict = {"name": s.name, "position": s.position, "content": s.content}
            gates = s.get_gates()
            if gates:
                step_data["gates"] = gates
            ifs = s.get_ifs()
            if ifs:
                step_data["ifs"] = ifs
            if s.agent_alias and s.agent_alias != "normal":
                step_data["agent_alias"] = s.agent_alias
            st = _normalize_step_type(s.step_type)
            if st != "agent":
                step_data["step_type"] = st
            if s.allow_max:
                step_data["allow_max"] = True
            if s.max_gate_retries is not None and s.max_gate_retries != 5:
                step_data["max_gate_retries"] = s.max_gate_retries
            skills = s.get_skills()
            if skills:
                step_data["skills"] = skills
            conns = s.get_connectors()
            if conns:
                step_data["connectors"] = conns
            flow_data["steps"].append(step_data)

        flows_dir = Path(space_path) / "flows"
        flows_dir.mkdir(parents=True, exist_ok=True)
        file_path = flows_dir / f"{flow.name}.json"
        file_path.write_text(json.dumps(flow_data, indent=2))
        return str(file_path)

    def export_flows(self, space_id: str, path: Optional[Path] = None) -> dict:
        """Export all flows for a space to a dict (optionally write to file)."""
        flows = self.list_by_space(space_id)
        data = {
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "flows": [],
        }
        for flow in flows:
            reqs = flow.get_requirements()
            flow_data = {
                "name": flow.name,
                "description": flow.description,
                "steps": [],
            }
            if reqs.get("connectors"):
                flow_data["requirements"] = reqs
            flow_variables = flow.get_variables()
            if flow_variables:
                flow_data["variables"] = flow_variables
            for s in sorted(flow.steps, key=lambda s: s.position):
                step_data = {"name": s.name, "position": s.position, "content": s.content}
                gates = s.get_gates()
                if gates:
                    step_data["gates"] = gates
                ifs = s.get_ifs()
                if ifs:
                    step_data["ifs"] = ifs
                if s.agent_alias and s.agent_alias != "normal":
                    step_data["agent_alias"] = s.agent_alias
                st = _normalize_step_type(s.step_type)
                if st != "agent":
                    step_data["step_type"] = st
                if s.allow_max:
                    step_data["allow_max"] = True
                if s.max_gate_retries is not None and s.max_gate_retries != 5:
                    step_data["max_gate_retries"] = s.max_gate_retries
                skills = s.get_skills()
                if skills:
                    step_data["skills"] = skills
                conns = s.get_connectors()
                if conns:
                    step_data["connectors"] = conns
                flow_data["steps"].append(step_data)
            data["flows"].append(flow_data)

        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(data, indent=2))

        return data

    def import_flows(self, path: Path, space_id: str) -> int:
        """Import flows from a JSON file. Upserts by name. Returns count imported."""
        data = json.loads(Path(path).read_text())
        return self._import_flows_data(data, space_id=space_id, skip_existing=False)

    def _import_flows_data(self, data: dict, space_id: str, skip_existing: bool = False) -> int:
        """Import flows from parsed JSON data."""
        count = 0
        for flow_data in data.get("flows", []):
            name = flow_data["name"]
            existing = self.get_by_name(name, space_id)

            if existing and skip_existing:
                continue

            if existing:
                for step in list(existing.steps):
                    self.session.delete(step)
                existing.description = flow_data.get("description", "")
                reqs = flow_data.get("requirements")
                if reqs:
                    existing.requirements = json.dumps(reqs)
                imported_vars = flow_data.get("variables")
                if imported_vars:
                    normalized = {}
                    for k, v in imported_vars.items():
                        normalized[k] = v if isinstance(v, dict) else {"value": str(v) if v else "", "is_env": False}
                    existing_vars = existing.get_variables()
                    merged = dict(existing_vars)
                    for k, v in normalized.items():
                        if k in merged and not v.get("value") and merged[k].get("value"):
                            merged[k] = {**v, "value": merged[k]["value"]}
                        else:
                            merged[k] = v
                    existing.variables = json.dumps(merged)
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
                        agent_alias=step_data.get("agent_alias", "normal"),
                        step_type=_normalize_step_type(step_data.get("step_type")),
                        allow_max=step_data.get("allow_max", False),
                        max_gate_retries=step_data.get("max_gate_retries", 5),
                        skills=_serialize_json_list(step_data.get("skills")),
                        connectors=_serialize_json_list(step_data.get("connectors")),
                    )
                    self.session.add(step)
            else:
                self.create(
                    name=name,
                    space_id=space_id,
                    description=flow_data.get("description", ""),
                    steps=flow_data.get("steps", []),
                    requirements=flow_data.get("requirements"),
                    variables=flow_data.get("variables"),
                )
            count += 1

        self.session.commit()
        return count

    def sync_from_disk(self, space_path: str, space_id: str) -> int:
        """Discover flow JSON files in <space>/flows/ and import them.

        Each .json file should follow the standard export format (with a
        top-level ``flows`` array) or be a single-flow shorthand (a dict
        with ``name`` and ``steps`` at the top level).

        Returns the number of flows synced.
        """
        flows_dir = Path(space_path) / "flows"
        if not flows_dir.is_dir():
            return 0

        count = 0
        for flow_file in sorted(flows_dir.glob("*.json")):
            try:
                data = json.loads(flow_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            if "flows" in data:
                count += self._import_flows_data(data, space_id=space_id, skip_existing=True)
            elif "name" in data and "steps" in data:
                wrapped = {"version": 1, "flows": [data]}
                count += self._import_flows_data(wrapped, space_id=space_id, skip_existing=True)

        return count

    def validate_flow(self, flow_id: str, space_id: Optional[str] = None) -> list[dict]:
        """Validate a flow's configuration. Returns a list of warning dicts."""
        from ..config import AGENT_REGISTRY
        from ..db.models import AgentAlias, AgentConfig

        flow = self.get(flow_id)
        if not flow:
            return [{"step_name": "", "warning_type": "missing_flow", "message": "Flow not found"}]

        warnings: list[dict] = []

        flow_vars = flow.get_variables()
        for var_name, var_entry in flow_vars.items():
            val = var_entry["value"] if isinstance(var_entry, dict) else var_entry
            if not val:
                warnings.append({
                    "step_name": "",
                    "warning_type": "missing_variable",
                    "variable_key": var_name,
                    "message": f"Variable '{var_name}' has no value. Fill it in on the flow page before running.",
                })

        from ..db.models import McpConnector
        enabled_connectors = {
            c.server_id
            for c in self.session.query(McpConnector).filter_by(enabled=True).all()
        }
        warned_connectors: set[str] = set()
        for step in flow.steps:
            for connector in step.get_connectors():
                if connector not in warned_connectors and connector not in enabled_connectors:
                    warnings.append({
                        "step_name": step.name,
                        "warning_type": "missing_connector",
                        "message": f"Connector '{connector}' is not enabled. Enable it in Settings > Connectors.",
                    })
                    warned_connectors.add(connector)

        for step in flow.steps:
            st = _normalize_step_type(step.step_type)
            alias_name = step.agent_alias or "normal"

            alias_type = "code" if st == "code" else "pi"
            alias = self.session.query(AgentAlias).filter_by(
                type=alias_type, name=alias_name,
            ).first()
            if not alias:
                warnings.append({
                    "step_name": step.name,
                    "warning_type": "missing_alias",
                    "message": f"Alias '{alias_name}' not found for type '{alias_type}'. Configure it on the Agents page.",
                })
                continue

            agent_key = alias.agent
            reg = AGENT_REGISTRY.get(agent_key, {})

            if reg.get("type") == "code":
                binary = reg.get("binary", agent_key)
                if not shutil.which(binary):
                    warnings.append({
                        "step_name": step.name,
                        "warning_type": "missing_binary",
                        "message": f"Binary '{binary}' for agent '{agent_key}' not found on PATH.",
                    })
            elif reg.get("type") == "chat":
                api_key_env = reg.get("api_key_env", "")
                if api_key_env:
                    import os
                    has_env = bool(os.environ.get(api_key_env))
                    has_db = False
                    if not has_env:
                        cfg = self.session.query(AgentConfig).filter_by(
                            agent=agent_key, key=api_key_env,
                        ).first()
                        has_db = bool(cfg and cfg.value)
                    if not has_env and not has_db:
                        warnings.append({
                            "step_name": step.name,
                            "warning_type": "missing_api_key",
                            "message": f"API key '{api_key_env}' not configured for provider '{agent_key}'. "
                                       f"Set it as an env variable or in agent config on the Agents page.",
                        })

        return warnings
