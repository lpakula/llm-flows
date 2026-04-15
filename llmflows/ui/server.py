"""FastAPI server for the llmflows web UI."""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..config import AGENT_REGISTRY, KNOWN_AGENTS, KNOWN_MODELS, load_system_config, save_system_config
from ..db.database import get_session, reset_engine
from ..services.agent import AgentService
from ..services.flow import FlowService
from ..services.project import ProjectService
from ..services.run import RunService
from ..services.skill import SkillService

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="llmflows", version=__version__)


# --- Pydantic models ---

class FlowCreate(BaseModel):
    name: str
    description: str = ""
    copy_from: Optional[str] = None


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class StepCreate(BaseModel):
    name: str
    content: str = ""
    position: Optional[int] = None
    gates: Optional[list[dict]] = None
    ifs: Optional[list[dict]] = None
    agent_alias: str = "standard"
    step_type: str = "agent"
    allow_max: bool = False
    max_gate_retries: int = 3
    skills: Optional[list[str]] = None


class StepUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    position: Optional[int] = None
    gates: Optional[list[dict]] = None
    ifs: Optional[list[dict]] = None
    agent_alias: Optional[str] = None
    step_type: Optional[str] = None
    allow_max: Optional[bool] = None
    max_gate_retries: Optional[int] = None
    skills: Optional[list[str]] = None


class StepRespondBody(BaseModel):
    response: str = ""


class ReorderSteps(BaseModel):
    step_ids: list[str]


class ScheduleBody(BaseModel):
    flow_id: str
    one_shot: bool = False


class DaemonConfigBody(BaseModel):
    poll_interval_seconds: Optional[int] = None
    run_timeout_minutes: Optional[int] = None
    gate_timeout_seconds: Optional[int] = None


class GatewayConfigBody(BaseModel):
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_allowed_chat_ids: Optional[list[int]] = None


class ProjectSettingsUpdate(BaseModel):
    is_git_repo: Optional[bool] = None
    max_concurrent_tasks: Optional[int] = None


# --- Helpers ---

def _get_services():
    reset_engine()
    session = get_session()
    return session, ProjectService(session)


ATTACHMENTS_DIR = Path.home() / ".llmflows" / "attachments"

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


# --- Root ---

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# --- Daemon endpoints ---

@app.get("/api/daemon/status")
async def daemon_status():
    from ..services.daemon import read_pid_file
    pid = read_pid_file()
    return {"running": pid is not None, "pid": pid}


@app.get("/api/daemon/logs")
async def daemon_logs(lines: int = 200):
    log_path = os.path.expanduser("~/.llmflows/daemon.log")
    if not os.path.exists(log_path):
        return {"lines": []}
    with open(log_path, "r") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return {"lines": [line.rstrip() for line in tail]}


@app.get("/api/config/daemon")
async def get_daemon_config():
    config = load_system_config()
    return config.get("daemon", {})


@app.patch("/api/config/daemon")
async def update_daemon_config(body: DaemonConfigBody):
    config = load_system_config()
    if "daemon" not in config:
        config["daemon"] = {}
    if "ui" not in config:
        config["ui"] = {}
    if body.poll_interval_seconds is not None:
        config["daemon"]["poll_interval_seconds"] = body.poll_interval_seconds
    if body.run_timeout_minutes is not None:
        config["daemon"]["run_timeout_minutes"] = body.run_timeout_minutes
    if body.gate_timeout_seconds is not None:
        config["daemon"]["gate_timeout_seconds"] = body.gate_timeout_seconds
    save_system_config(config)
    return config["daemon"]


@app.get("/api/config/gateway")
async def get_gateway_config():
    config = load_system_config()
    tg = config.get("telegram", {})
    return {
        "telegram_enabled": tg.get("enabled", False),
        "telegram_bot_token": tg.get("bot_token", ""),
        "telegram_allowed_chat_ids": tg.get("allowed_chat_ids", []),
    }


@app.patch("/api/config/gateway")
async def update_gateway_config(body: GatewayConfigBody):
    config = load_system_config()
    if "telegram" not in config:
        config["telegram"] = {}
    if body.telegram_enabled is not None:
        config["telegram"]["enabled"] = body.telegram_enabled
    if body.telegram_bot_token is not None:
        config["telegram"]["bot_token"] = body.telegram_bot_token
    if body.telegram_allowed_chat_ids is not None:
        config["telegram"]["allowed_chat_ids"] = body.telegram_allowed_chat_ids
    save_system_config(config)
    tg = config["telegram"]
    return {
        "telegram_enabled": tg.get("enabled", False),
        "telegram_bot_token": tg.get("bot_token", ""),
        "telegram_allowed_chat_ids": tg.get("allowed_chat_ids", []),
    }


@app.post("/api/daemon/stop")
async def stop_daemon():
    import signal
    from ..services.daemon import read_pid_file, remove_pid_file

    pid = read_pid_file()
    if not pid:
        return {"ok": True, "running": False, "pid": None}

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    remove_pid_file()

    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return {"ok": True, "running": False, "pid": None}

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    return {"ok": True, "running": False, "pid": None}


@app.post("/api/daemon/start")
async def start_daemon():
    import shutil
    import subprocess
    import sys
    from ..services.daemon import read_pid_file

    if read_pid_file():
        pid = read_pid_file()
        return {"ok": True, "running": True, "pid": pid}

    llmflows_bin = shutil.which("llmflows")
    if llmflows_bin:
        cmd = [llmflows_bin, "daemon", "start"]
    else:
        cmd = [sys.executable, "-m", "llmflows", "daemon", "start"]

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    for _ in range(10):
        await asyncio.sleep(0.5)
        new_pid = read_pid_file()
        if new_pid:
            return {"ok": True, "running": True, "pid": new_pid}

    return {"ok": False, "running": False, "pid": None, "error": "Daemon did not start in time"}


# --- Project endpoints ---

@app.get("/api/projects")
async def list_projects():
    session, project_svc = _get_services()
    try:
        projects = project_svc.list_all()
        return [p.to_dict() for p in projects]
    finally:
        session.close()


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.to_dict()
    finally:
        session.close()


class ProjectUpdate(BaseModel):
    name: Optional[str] = None


@app.patch("/api/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if updates:
            project = project_svc.update(project_id, **updates)
        return project.to_dict()
    finally:
        session.close()


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    session, project_svc = _get_services()
    try:
        if not project_svc.unregister(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        return {"ok": True}
    finally:
        session.close()


@app.get("/api/projects/{project_id}/settings")
async def get_project_settings(project_id: str):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return {
            "is_git_repo": project.is_git_repo if project.is_git_repo is not None else True,
            "max_concurrent_tasks": project.max_concurrent_tasks if project.max_concurrent_tasks is not None else 1,
        }
    finally:
        session.close()


@app.patch("/api/projects/{project_id}/settings")
async def update_project_settings(project_id: str, body: ProjectSettingsUpdate):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        updates = {}
        if body.is_git_repo is not None:
            updates["is_git_repo"] = body.is_git_repo
        if body.max_concurrent_tasks is not None:
            updates["max_concurrent_tasks"] = max(1, body.max_concurrent_tasks)
        if updates:
            project_svc.update(project_id, **updates)
            session.refresh(project)

        return {
            "is_git_repo": project.is_git_repo if project.is_git_repo is not None else True,
            "max_concurrent_tasks": project.max_concurrent_tasks if project.max_concurrent_tasks is not None else 1,
        }
    finally:
        session.close()


@app.get("/api/projects/{project_id}/variables")
async def get_project_variables(project_id: str):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.get_variables()
    finally:
        session.close()


class VariableUpdate(BaseModel):
    value: str


@app.put("/api/projects/{project_id}/variables/{key}")
async def set_project_variable(project_id: str, key: str, body: VariableUpdate):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        variables = project.get_variables()
        variables[key] = body.value
        project_svc.update(project_id, variables=json.dumps(variables))
        return variables
    finally:
        session.close()


@app.delete("/api/projects/{project_id}/variables/{key}")
async def delete_project_variable(project_id: str, key: str):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        variables = project.get_variables()
        if key not in variables:
            raise HTTPException(status_code=404, detail=f"Variable '{key}' not found")
        del variables[key]
        project_svc.update(project_id, variables=json.dumps(variables))
        return variables
    finally:
        session.close()


# --- Schedule flow run ---

@app.post("/api/projects/{project_id}/schedule")
async def schedule_flow_run(project_id: str, body: ScheduleBody):
    """Schedule a new FlowRun for a flow."""
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        run_svc = RunService(session)
        flow_svc = FlowService(session)

        flow = flow_svc.get(body.flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")

        one_shot = body.one_shot
        if one_shot and flow_svc.has_human_steps(flow.name, project_id=project_id):
            one_shot = False

        run = run_svc.enqueue(project_id, body.flow_id, one_shot=one_shot)
        return run.to_dict()
    finally:
        session.close()


# --- FlowRun endpoints ---

@app.get("/api/projects/{project_id}/runs")
async def list_project_runs(project_id: str):
    """All flow runs for a project (for the Board page)."""
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        run_svc = RunService(session)
        runs = run_svc.list_by_project(project_id)
        result = []
        for r in runs:
            d = r.to_dict()
            run_att_dir = ATTACHMENTS_DIR / r.id
            if run_att_dir.is_dir():
                d["attachments"] = sorted(
                    [{"name": f.name, "url": f"/api/attachments/{r.id}/{f.name}"}
                     for f in run_att_dir.iterdir() if f.is_file()],
                    key=lambda x: x["name"],
                )
            else:
                d["attachments"] = []
            result.append(d)
        return result
    finally:
        session.close()


class ResumeBody(BaseModel):
    prompt: str = ""


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: str):
    """Pause an active run -- kills agent, marks as paused (not completed)."""
    session, project_svc = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.completed_at:
            raise HTTPException(status_code=400, detail="Run is already completed")

        project = project_svc.get(run.project_id) if run.project_id else None
        if project:
            AgentService.kill_agent(project.path, run_id=run.id)

        run_svc.pause(run_id)
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str, body: ResumeBody):
    """Resume a paused run, optionally with an additional prompt."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if not run.paused_at:
            raise HTTPException(status_code=400, detail="Run is not paused")
        run_svc.resume(run_id, body.prompt)
        return {"ok": True}
    finally:
        session.close()


class RetryStepBody(BaseModel):
    step_name: str


@app.post("/api/runs/{run_id}/retry-step")
async def retry_step(run_id: str, body: RetryStepBody):
    """Re-activate an interrupted run and re-run from a specific step."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.retry_step(run_id, body.step_name)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/step-runs/{step_run_id}/complete")
async def complete_step_manually(step_run_id: str):
    """Manually mark a step as completed so the flow can advance."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        sr = run_svc.complete_step_manually(step_run_id)
        if not sr:
            raise HTTPException(status_code=404, detail="StepRun not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str):
    """Stop or dequeue a run."""
    session, project_svc = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.completed_at:
            raise HTTPException(status_code=400, detail="Run is already completed")

        if not run.started_at:
            session.delete(run)
            session.commit()
            return {"ok": True, "killed": False, "dequeued": True}

        run_svc.mark_completed(run_id, outcome="cancelled")

        project = project_svc.get(run.project_id) if run.project_id else None
        killed = False
        if project:
            killed = AgentService.kill_agent(project.path, run_id=run.id)

        return {"ok": True, "killed": killed, "dequeued": False}
    finally:
        session.close()


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a completed or queued (not yet started) flow run by ID."""
    session, _ = _get_services()
    try:
        from ..db.models import FlowRun
        run = session.query(FlowRun).filter_by(id=run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.started_at and not run.completed_at:
            raise HTTPException(status_code=400, detail="Cannot delete an active run")
        session.delete(run)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.get("/api/runs/{run_id}/steps")
async def get_run_steps(run_id: str):
    """Return step progress for a run, including all retry attempts."""
    session, _ = _get_services()
    try:
        from ..db.models import FlowRun
        run = session.query(FlowRun).filter_by(id=run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        run_svc = RunService(session)
        flow_svc = FlowService(session)
        step_runs = run_svc.list_step_runs(run_id)

        one_shot_sr = next(
            (sr for sr in step_runs if sr.step_name == "__one_shot__"), None
        )
        if one_shot_sr or bool(run.one_shot):
            result = []
            if one_shot_sr:
                result.append({
                    "name": "__one_shot__",
                    "flow": one_shot_sr.flow_name,
                    "status": one_shot_sr.status,
                    "has_ifs": False,
                    "step_run": one_shot_sr.to_dict(),
                    "attempts": [one_shot_sr.to_dict()],
                })
            return {"steps": result}

        step_runs_by_name: dict[str, list] = {}
        for sr in step_runs:
            step_runs_by_name.setdefault(sr.step_name, []).append(sr)

        step_run_map = {}
        for name, srs in step_runs_by_name.items():
            step_run_map[name] = max(srs, key=lambda s: s.started_at or s.created_at if hasattr(s, 'created_at') else s.started_at)

        max_started_position = -1
        for sr in step_runs:
            if sr.started_at and sr.step_position > max_started_position:
                max_started_position = sr.step_position

        result = []

        snap_steps = []
        if run.flow_snapshot:
            try:
                snap = json.loads(run.flow_snapshot)
                snap_steps = sorted(snap.get("steps", []), key=lambda s: s.get("position", 0))
            except (json.JSONDecodeError, TypeError):
                pass

        step_sources = snap_steps or []
        if not step_sources and run.flow_name:
            for sname in flow_svc.get_flow_steps(run.flow_name, project_id=run.project_id):
                obj = flow_svc.get_step_obj(run.flow_name, sname, project_id=run.project_id)
                step_sources.append({
                    "name": sname,
                    "ifs": obj.get_ifs() if obj else [],
                    "agent_alias": obj.agent_alias if obj else "standard",
                    "allow_max": bool(obj.allow_max) if obj else False,
                    "max_gate_retries": obj.max_gate_retries if obj else 5,
                })

        from ..services.context import ContextService
        project = run.project

        for position, step_src in enumerate(step_sources):
            step_name = step_src["name"]
            has_ifs = bool(step_src.get("ifs"))
            sr = step_run_map.get(step_name)
            attempts = [s.to_dict() for s in sorted(step_runs_by_name.get(step_name, []), key=lambda s: s.attempt or 0)]
            if sr:
                status = sr.status
                step_data = sr.to_dict()
                if sr.awaiting_user_at and not sr.completed_at and project:
                    try:
                        artifacts_dir = ContextService.get_artifacts_dir(
                            Path(project.path), run_id,
                        )
                        result_file = artifacts_dir / f"{sr.step_position:02d}-{sr.step_name}" / "_result.md"
                        if result_file.exists():
                            step_data["user_message"] = result_file.read_text().strip()
                    except (PermissionError, OSError):
                        pass
            else:
                status = "skipped" if has_ifs and position < max_started_position else "pending"
                step_data = None
            result.append({
                "name": step_name,
                "flow": run.flow_name or "",
                "status": status,
                "has_ifs": has_ifs,
                "step_run": step_data,
                "attempts": attempts,
                "agent_alias": step_src.get("agent_alias", "standard"),
                "step_type": step_src.get("step_type", "agent"),
                "allow_max": bool(step_src.get("allow_max", False)),
                "max_gate_retries": step_src.get("max_gate_retries", 5),
            })

        summary_sr = step_run_map.get("__summary__")
        if summary_sr and not any(s["name"] == "__summary__" for s in result):
            result.append({
                "name": "__summary__",
                "flow": run.flow_name or "",
                "status": summary_sr.status,
                "has_ifs": False,
                "step_run": summary_sr.to_dict(),
                "attempts": [summary_sr.to_dict()],
            })

        return {"steps": result}
    finally:
        session.close()


@app.get("/api/step-runs/{step_run_id}/logs")
async def stream_step_run_logs(step_run_id: str):
    """SSE endpoint that tails a StepRun's log file."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        sr = run_svc.get_step_run(step_run_id)
        if not sr:
            raise HTTPException(status_code=404, detail="StepRun not found")
        if not sr.log_path:
            raise HTTPException(status_code=404, detail="No log path set for this step run")
        log_path = Path(sr.log_path)
        is_completed = sr.completed_at is not None
    finally:
        session.close()

    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found on disk")

    async def tail_log():
        pos = 0
        idle_count = 0
        max_idle = 5 if is_completed else 120
        while idle_count < max_idle:
            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                break

            if size > pos:
                idle_count = 0
                with open(log_path, "r") as f:
                    f.seek(pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            yield f"data: {json.dumps(event)}\n\n"
                        except json.JSONDecodeError:
                            yield f"data: {json.dumps({'type': 'raw', 'text': line})}\n\n"
                    pos = f.tell()
            else:
                idle_count += 1

            await asyncio.sleep(1)

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        tail_log(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/logs")
async def stream_run_logs(run_id: str):
    """SSE endpoint that tails the agent's NDJSON log file for a FlowRun."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if not run.log_path:
            raise HTTPException(status_code=404, detail="No log path set for this run")
        log_path = Path(run.log_path)
    finally:
        session.close()

    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found on disk")

    async def tail_log():
        pos = 0
        idle_count = 0
        max_idle = 120
        while idle_count < max_idle:
            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                break

            if size > pos:
                idle_count = 0
                with open(log_path, "r") as f:
                    f.seek(pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            yield f"data: {json.dumps(event)}\n\n"
                        except json.JSONDecodeError:
                            yield f"data: {json.dumps({'type': 'raw', 'text': line})}\n\n"
                    pos = f.tell()
            else:
                idle_count += 1

            await asyncio.sleep(1)

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        tail_log(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Attachments ---

@app.get("/api/attachments/{run_id}/{filename}")
async def serve_attachment(run_id: str, filename: str):
    path = ATTACHMENTS_DIR / run_id / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(str(path))


# --- Agent Alias endpoints ---

class AgentAliasCreate(BaseModel):
    name: str
    agent: str = "cursor"
    model: str


class AgentAliasUpdate(BaseModel):
    name: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[str] = None
    position: Optional[int] = None


@app.get("/api/agent-aliases")
async def list_agent_aliases():
    from ..db.models import AgentAlias
    session, _ = _get_services()
    try:
        aliases = session.query(AgentAlias).order_by(AgentAlias.position, AgentAlias.name).all()
        return [a.to_dict() for a in aliases]
    finally:
        session.close()


@app.post("/api/agent-aliases")
async def create_agent_alias(body: AgentAliasCreate):
    from ..db.models import AgentAlias
    session, _ = _get_services()
    try:
        existing = session.query(AgentAlias).filter_by(name=body.name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Alias '{body.name}' already exists")
        max_pos = session.query(AgentAlias).count()
        alias = AgentAlias(
            name=body.name, agent=body.agent, model=body.model,
            position=max_pos,
        )
        session.add(alias)
        session.commit()
        return alias.to_dict()
    finally:
        session.close()


@app.patch("/api/agent-aliases/{alias_id}")
async def update_agent_alias(alias_id: str, body: AgentAliasUpdate):
    from ..db.models import AgentAlias
    session, _ = _get_services()
    try:
        alias = session.query(AgentAlias).filter_by(id=alias_id).first()
        if not alias:
            raise HTTPException(status_code=404, detail="Alias not found")
        if body.name is not None:
            dup = session.query(AgentAlias).filter_by(name=body.name).first()
            if dup and dup.id != alias_id:
                raise HTTPException(status_code=400, detail=f"Alias '{body.name}' already exists")
            alias.name = body.name
        if body.agent is not None:
            alias.agent = body.agent
        if body.model is not None:
            alias.model = body.model
        if body.position is not None:
            alias.position = body.position
        session.commit()
        return alias.to_dict()
    finally:
        session.close()


@app.delete("/api/agent-aliases/{alias_id}")
async def delete_agent_alias(alias_id: str):
    from ..db.models import AgentAlias
    session, _ = _get_services()
    try:
        alias = session.query(AgentAlias).filter_by(id=alias_id).first()
        if not alias:
            raise HTTPException(status_code=404, detail="Alias not found")
        session.delete(alias)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


# --- Queue + dashboard ---

@app.get("/api/queue")
async def global_queue():
    """All active FlowRuns globally (executing first, then pending)."""
    session, project_svc = _get_services()
    try:
        run_svc = RunService(session)
        runs = run_svc.list_active()
        result = []
        for r in runs:
            d = r.to_dict()
            project = project_svc.get(r.project_id) if r.project_id else None
            d["project_name"] = project.name if project else None
            result.append(d)
        return result
    finally:
        session.close()


@app.get("/api/projects/{project_id}/queue")
async def project_queue(project_id: str):
    """All FlowRuns for project (pending + executing), ordered."""
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        run_svc = RunService(session)
        runs = run_svc.list_by_project(project_id)
        active = [r.to_dict() for r in runs if r.completed_at is None]
        return active
    finally:
        session.close()


@app.get("/api/dashboard")
async def dashboard():
    """System overview: all projects with active run counts, queue depths."""
    session, project_svc = _get_services()
    try:
        run_svc = RunService(session)
        projects = project_svc.list_all()
        result = []
        for p in projects:
            all_runs = run_svc.list_by_project(p.id)
            active_runs = [r for r in all_runs if r.completed_at is None]
            pending_runs = [r for r in active_runs if r.started_at is None]
            executing_runs = [r for r in active_runs if r.started_at is not None]
            recent = [r.to_dict() for r in all_runs if r.completed_at is not None][-5:]

            run_counts = {
                "running": len(executing_runs),
                "queued": len(pending_runs),
            }

            result.append({
                "project": p.to_dict(),
                "run_counts": run_counts,
                "queue_depth": len(pending_runs),
                "active_runs": len(executing_runs),
                "executing": [
                    {
                        "run": r.to_dict(),
                        "agent_active": AgentService.is_agent_running(p.path, run_id=r.id),
                    }
                    for r in executing_runs
                ],
                "recent_completions": recent,
            })
        return result
    finally:
        session.close()


# --- Inbox endpoints ---

@app.get("/api/inbox")
async def get_inbox():
    """Return inbox items (awaiting_user + completed_run), enriched with context."""
    from ..services.context import ContextService
    from ..db.models import Project as ProjectModel, StepRun, FlowRun
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        inbox_items = run_svc.list_inbox()

        awaiting = []
        completed = []

        for item in inbox_items:
            if item.type == "awaiting_user":
                sr = session.query(StepRun).filter_by(id=item.reference_id).first()
                if not sr or sr.completed_at:
                    run_svc.archive_inbox_item(item.id)
                    continue
                run = session.query(FlowRun).filter_by(id=sr.flow_run_id).first()
                project = session.query(ProjectModel).filter_by(id=item.project_id).first()
                if not run or not project:
                    continue

                step_type = "agent"
                if run.flow_snapshot:
                    try:
                        snap = json.loads(run.flow_snapshot)
                        for s in snap.get("steps", []):
                            if s["name"] == sr.step_name:
                                step_type = s.get("step_type", "agent")
                                break
                    except (ValueError, KeyError, TypeError):
                        pass

                user_message = ""
                try:
                    artifacts_dir = ContextService.get_artifacts_dir(
                        Path(project.path), run.id,
                    )
                    result_file = artifacts_dir / f"{sr.step_position:02d}-{sr.step_name}" / "_result.md"
                    if result_file.exists():
                        user_message = result_file.read_text().strip()
                except (PermissionError, OSError):
                    pass

                awaiting.append({
                    "inbox_id": item.id,
                    "step_run_id": sr.id,
                    "step_name": sr.step_name,
                    "step_type": step_type,
                    "step_position": sr.step_position,
                    "project_id": project.id,
                    "project_name": project.name,
                    "run_id": run.id,
                    "flow_name": run.flow_name or "",
                    "prompt": sr.prompt or "",
                    "user_message": user_message,
                    "log_path": sr.log_path or "",
                    "awaiting_since": (sr.awaiting_user_at.isoformat() + "Z") if sr.awaiting_user_at else None,
                })

            elif item.type == "completed_run":
                run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                project = session.query(ProjectModel).filter_by(id=item.project_id).first()
                if not run or not project:
                    continue

                run_att_dir = ATTACHMENTS_DIR / run.id
                attachments = []
                if run_att_dir.is_dir():
                    attachments = sorted(
                        [{"name": f.name, "url": f"/api/attachments/{run.id}/{f.name}"}
                         for f in run_att_dir.iterdir() if f.is_file()],
                        key=lambda x: x["name"],
                    )

                completed.append({
                    "inbox_id": item.id,
                    "run_id": run.id,
                    "project_id": project.id,
                    "project_name": project.name,
                    "flow_name": run.flow_name or "",
                    "outcome": run.outcome or "",
                    "summary": run.summary or "",
                    "duration_seconds": run.duration_seconds,
                    "completed_at": (run.completed_at.isoformat() + "Z") if run.completed_at else None,
                    "attachments": attachments,
                })

        return {"awaiting": awaiting, "completed": completed, "count": len(awaiting) + len(completed)}
    finally:
        session.close()


@app.post("/api/inbox/{item_id}/archive")
async def archive_inbox_item(item_id: str):
    """Archive an inbox item (dismiss it)."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        ok = run_svc.archive_inbox_item(item_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Inbox item not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/step-runs/{step_run_id}/respond")
async def respond_to_step(step_run_id: str, body: StepRespondBody):
    """User responds to an awaiting_user step (confirm manual or answer prompt)."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        sr = run_svc.respond_to_step(step_run_id, body.response)
        if not sr:
            raise HTTPException(status_code=404, detail="StepRun not found or not awaiting user")
        return {"ok": True}
    finally:
        session.close()


# --- Flow endpoints (project-scoped) ---

@app.get("/api/projects/{project_id}/flows")
async def list_project_flows(project_id: str):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        flow_svc = FlowService(session)
        flows = flow_svc.list_by_project(project_id)
        return [
            {
                "id": f.id,
                "project_id": f.project_id,
                "name": f.name,
                "description": f.description,
                "step_count": len(f.steps),
                "steps": [
                    {"name": s.name, "position": s.position, "step_type": s.step_type or "agent"}
                    for s in sorted(f.steps, key=lambda s: s.position)
                ],
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in flows
        ]
    finally:
        session.close()


@app.post("/api/projects/{project_id}/flows/export")
async def export_project_flows(project_id: str):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        flow_svc = FlowService(session)
        data = flow_svc.export_flows(project_id)
        return JSONResponse(content=data)
    finally:
        session.close()


@app.post("/api/projects/{project_id}/flows/import")
async def import_project_flows(project_id: str, file: UploadFile = File(...)):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        content = await file.read()
        data = json.loads(content)
        flow_svc = FlowService(session)
        count = flow_svc._import_flows_data(data, project_id=project_id, skip_existing=False)
        return {"imported": count}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    finally:
        session.close()


@app.get("/api/flows/{flow_id}")
async def get_flow(flow_id: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flow = flow_svc.get(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        return flow.to_dict()
    finally:
        session.close()


@app.post("/api/projects/{project_id}/flows")
async def create_project_flow(project_id: str, body: FlowCreate):
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        flow_svc = FlowService(session)
        if body.copy_from:
            flow = flow_svc.duplicate(body.copy_from, body.name, project_id=project_id)
            if not flow:
                raise HTTPException(status_code=404, detail=f"Source flow '{body.copy_from}' not found")
            if body.description:
                flow_svc.update(flow.id, description=body.description)
        else:
            flow = flow_svc.create(
                name=body.name,
                project_id=project_id,
                description=body.description,
            )
        return flow.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()


@app.patch("/api/flows/{flow_id}")
async def update_flow(flow_id: str, body: FlowUpdate):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.description is not None:
            updates["description"] = body.description
        flow = flow_svc.update(flow_id, **updates)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        return flow.to_dict()
    finally:
        session.close()


@app.delete("/api/flows/{flow_id}")
async def delete_flow(flow_id: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flow_svc.delete(flow_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()


@app.post("/api/flows/{flow_id}/steps")
async def add_flow_step(flow_id: str, body: StepCreate):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        step = flow_svc.add_step(
            flow_id, body.name, body.content, body.position,
            gates=body.gates, ifs=body.ifs,
            agent_alias=body.agent_alias, step_type=body.step_type,
            allow_max=body.allow_max,
            max_gate_retries=body.max_gate_retries,
            skills=body.skills,
        )
        if not step:
            raise HTTPException(status_code=404, detail="Flow not found")
        return step.to_dict()
    finally:
        session.close()


@app.patch("/api/flows/{flow_id}/steps/{step_id}")
async def update_flow_step(flow_id: str, step_id: str, body: StepUpdate):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.content is not None:
            updates["content"] = body.content
        if body.position is not None:
            updates["position"] = body.position
        if body.gates is not None:
            updates["gates"] = json.dumps(body.gates)
        if body.ifs is not None:
            updates["ifs"] = json.dumps(body.ifs)
        if body.agent_alias is not None:
            updates["agent_alias"] = body.agent_alias
        if body.step_type is not None:
            updates["step_type"] = body.step_type
        if body.allow_max is not None:
            updates["allow_max"] = body.allow_max
        if body.max_gate_retries is not None:
            updates["max_gate_retries"] = body.max_gate_retries
        if body.skills is not None:
            updates["skills"] = json.dumps(body.skills)
        step = flow_svc.update_step(step_id, **updates)
        if not step:
            raise HTTPException(status_code=404, detail="Step not found")
        return step.to_dict()
    finally:
        session.close()


@app.delete("/api/flows/{flow_id}/steps/{step_id}")
async def delete_flow_step(flow_id: str, step_id: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        if not flow_svc.remove_step(step_id):
            raise HTTPException(status_code=404, detail="Step not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/flows/{flow_id}/reorder")
async def reorder_flow_steps(flow_id: str, body: ReorderSteps):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        if not flow_svc.reorder_steps(flow_id, body.step_ids):
            raise HTTPException(status_code=404, detail="Flow not found")
        flow = flow_svc.get(flow_id)
        return flow.to_dict()
    finally:
        session.close()


# --- Skills endpoints ---

@app.get("/api/projects/{project_id}/skills")
async def list_project_skills(project_id: str):
    """Return discovered skills for a project."""
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        skills = SkillService.discover(project.path)
        return [{"name": s.name, "path": s.path, "description": s.description, "compatibility": s.compatibility} for s in skills]
    finally:
        session.close()


@app.get("/api/projects/{project_id}/skills/{skill_name}/content")
async def get_skill_content(project_id: str, skill_name: str):
    """Return the full SKILL.md content for a skill."""
    session, project_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        content = SkillService.get_content(project.path, skill_name)
        if content is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"content": content}
    finally:
        session.close()


@app.get("/api/agents")
async def list_agents():
    """Return only agents whose binary is found in PATH (ready to use)."""
    import shutil
    return [name for name in KNOWN_AGENTS if shutil.which(AGENT_REGISTRY[name]["binary"])]


@app.get("/api/agents/status")
async def agents_status():
    """Return availability status for all known agents."""
    import shutil
    result = {}
    for name, reg in AGENT_REGISTRY.items():
        binary_path = shutil.which(reg["binary"])
        result[name] = {
            "label": reg["label"],
            "available": binary_path is not None,
            "binary": reg["binary"],
            "binary_path": binary_path,
            "command": reg["command"],
        }
    return result



@app.get("/api/agents/{agent_name}/config")
async def get_agent_config(agent_name: str):
    from ..db.models import AgentConfig
    session, _ = _get_services()
    try:
        configs = session.query(AgentConfig).filter_by(agent=agent_name).all()
        return [c.to_dict() for c in configs]
    finally:
        session.close()


class AgentConfigBody(BaseModel):
    key: str
    value: str


@app.post("/api/agents/{agent_name}/config")
async def set_agent_config(agent_name: str, body: AgentConfigBody):
    from ..db.models import AgentConfig
    session, _ = _get_services()
    try:
        existing = session.query(AgentConfig).filter_by(agent=agent_name, key=body.key).first()
        if existing:
            existing.value = body.value
        else:
            session.add(AgentConfig(agent=agent_name, key=body.key, value=body.value))
        session.commit()
        configs = session.query(AgentConfig).filter_by(agent=agent_name).all()
        return [c.to_dict() for c in configs]
    finally:
        session.close()


@app.delete("/api/agents/{agent_name}/config/{config_id}")
async def delete_agent_config(agent_name: str, config_id: str):
    from ..db.models import AgentConfig
    session, _ = _get_services()
    try:
        config = session.query(AgentConfig).filter_by(id=config_id, agent=agent_name).first()
        if not config:
            raise HTTPException(status_code=404, detail="Config not found")
        session.delete(config)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.get("/api/models")
async def list_models(agent: Optional[str] = None):
    """Return models for a specific agent, or all models if no agent specified."""
    if agent and agent in AGENT_REGISTRY:
        return AGENT_REGISTRY[agent]["models"]
    return KNOWN_MODELS


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{path:path}")
async def spa_fallback(path: str):
    """Serve index.html for any non-API path (SPA client-side routing)."""
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(
        content=(
            "<html><body style='font-family:monospace;padding:2rem'>"
            "<h2>UI not built</h2>"
            "<p>The React frontend was not compiled during installation.</p>"
            "<p>Run the following inside the package source directory to build it:</p>"
            "<pre>cd llmflows/ui/frontend && npm install && npm run build</pre>"
            "<p>Or reinstall with Node.js available so the build hook can run automatically.</p>"
            "</body></html>"
        ),
        status_code=503,
    )
