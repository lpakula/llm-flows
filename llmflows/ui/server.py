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
from ..db.models import TaskType
from ..services.agent import AgentService
from ..services.flow import FlowService
from ..services.project import ProjectService
from ..services.run import RunService
from ..services.task import TaskService
from ..services.worktree import WorktreeService

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="llmflows", version=__version__)


# --- Pydantic models ---

class TaskCreate(BaseModel):
    title: str
    description: str = ""
    type: str = "feature"
    default_flow_name: Optional[str] = None
    task_status: str = "backlog"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    default_flow_name: Optional[str] = None
    task_status: Optional[str] = None
    type: Optional[str] = None


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


class StepRespondBody(BaseModel):
    response: str = ""


class ReorderSteps(BaseModel):
    step_ids: list[str]


class TaskStartBody(BaseModel):
    flow: Optional[str] = None
    user_prompt: str = ""
    one_shot: bool = False


class DaemonConfigBody(BaseModel):
    poll_interval_seconds: Optional[int] = None
    run_timeout_minutes: Optional[int] = None
    gate_timeout_seconds: Optional[int] = None


class ProjectSettingsUpdate(BaseModel):
    is_git_repo: Optional[bool] = None


# --- Helpers ---

def _get_services():
    reset_engine()
    session = get_session()
    return session, ProjectService(session), TaskService(session)


def _enrich_task(task_dict: dict, project_path: str, session, project: Optional[object] = None) -> dict:
    """Add dynamic fields from active TaskRun and run count."""
    run_svc = RunService(session)
    active_run = run_svc.get_active(task_dict["id"])
    all_runs = run_svc.list_by_task(task_dict["id"])

    is_git = (project.is_git_repo if project is not None else None)
    if is_git is None:
        is_git = True
    branch = task_dict.get("worktree_branch", "")

    task_dict["agent_active"] = bool(active_run) and AgentService.is_agent_running(
        project_path,
        branch if is_git else "",
        task_id="" if is_git else task_dict["id"],
    )
    task_dict["flow"] = active_run.flow_name if active_run else None
    task_dict["current_step"] = active_run.current_step if active_run else None
    task_dict["run_id"] = active_run.id if active_run else None
    task_dict["run_count"] = len(all_runs)
    last_run = all_runs[0] if all_runs else None
    task_dict["last_run_status"] = last_run.status if last_run else None
    task_dict["last_run_outcome"] = last_run.outcome if last_run else None
    task_dict["last_run_started_at"] = last_run.started_at.isoformat() if last_run and last_run.started_at else None
    task_dict["last_run_completed_at"] = last_run.completed_at.isoformat() if last_run and last_run.completed_at else None
    task_dict["last_run_duration_seconds"] = last_run.duration_seconds if last_run else None
    if is_git and branch:
        wt_svc = WorktreeService(project_path)
        wt_path = wt_svc.get_worktree_path(branch)
        task_dict["worktree_path"] = str(wt_path) if wt_path else None
    else:
        task_dict["worktree_path"] = None
    return task_dict


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

    # Daemon is a long-running process — launch it detached and don't wait for it
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Give it a moment to write its PID file
    for _ in range(10):
        await asyncio.sleep(0.5)
        new_pid = read_pid_file()
        if new_pid:
            return {"ok": True, "running": True, "pid": new_pid}

    return {"ok": False, "running": False, "pid": None, "error": "Daemon did not start in time"}


# --- Project endpoints ---

@app.get("/api/projects")
async def list_projects():
    session, project_svc, _ = _get_services()
    try:
        projects = project_svc.list_all()
        return [p.to_dict() for p in projects]
    finally:
        session.close()


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    session, project_svc, _ = _get_services()
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
    session, project_svc, _ = _get_services()
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
    session, project_svc, _ = _get_services()
    try:
        if not project_svc.unregister(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        return {"ok": True}
    finally:
        session.close()


@app.get("/api/projects/{project_id}/settings")
async def get_project_settings(project_id: str):
    session, project_svc, _ = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"is_git_repo": project.is_git_repo if project.is_git_repo is not None else True}
    finally:
        session.close()


@app.patch("/api/projects/{project_id}/settings")
async def update_project_settings(project_id: str, body: ProjectSettingsUpdate):
    session, project_svc, _ = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if body.is_git_repo is not None:
            project_svc.update(project_id, is_git_repo=body.is_git_repo)
            session.refresh(project)

        return {"is_git_repo": project.is_git_repo if project.is_git_repo is not None else True}
    finally:
        session.close()


# --- Task endpoints ---

@app.get("/api/projects/{project_id}/tasks")
async def list_tasks(project_id: str):
    session, project_svc, task_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        tasks = task_svc.list_by_project(project_id)
        return [_enrich_task(t.to_dict(), project.path, session, project) for t in tasks]
    finally:
        session.close()


@app.post("/api/projects/{project_id}/tasks")
async def create_task(project_id: str, body: TaskCreate):
    session, project_svc, task_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        try:
            task_type = TaskType(body.type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid type: {body.type}")

        task = task_svc.create(
            project_id=project_id,
            name=body.title,
            description=body.description,
            task_type=task_type,
            default_flow_name=body.default_flow_name or None,
        )

        return _enrich_task(task.to_dict(), project.path, session, project)
    finally:
        session.close()


@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate):
    session, project_svc, task_svc = _get_services()
    try:
        task = task_svc.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        updates = {}
        if body.title is not None:
            updates["name"] = body.title
        if body.description is not None:
            updates["description"] = body.description
        if body.default_flow_name is not None:
            updates["default_flow_name"] = body.default_flow_name or None
        if body.task_status is not None:
            updates["task_status"] = body.task_status
        if body.type is not None:
            try:
                updates["type"] = TaskType(body.type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid type: {body.type}")
        if updates:
            task = task_svc.update(task_id, **updates)

        project = project_svc.get(task.project_id)
        return _enrich_task(task.to_dict(), project.path, session, project)
    finally:
        session.close()


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    session, _, task_svc = _get_services()
    try:
        if not task_svc.delete(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        return {"ok": True}
    finally:
        session.close()


ATTACHMENTS_DIR = Path.home() / ".llmflows" / "attachments"

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@app.post("/api/tasks/{task_id}/attachments")
async def upload_attachment(task_id: str, file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only image files are supported")
    task_dir = ATTACHMENTS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "image.png").suffix or ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = task_dir / filename
    dest.write_bytes(await file.read())
    return {"url": f"/api/attachments/{task_id}/{filename}", "filename": filename}


@app.get("/api/attachments/{task_id}/{filename}")
async def serve_attachment(task_id: str, filename: str):
    path = ATTACHMENTS_DIR / task_id / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(str(path))


@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: str, body: TaskStartBody):
    """Enqueue a new run for a task."""
    session, project_svc, task_svc = _get_services()
    try:
        task = task_svc.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        run_svc = RunService(session)
        flow_svc = FlowService(session)

        one_shot = body.one_shot
        if one_shot and body.flow and flow_svc.has_human_steps(body.flow, project_id=task.project_id):
            one_shot = False

        run_svc.enqueue(
            task.project_id, task_id,
            flow_name=body.flow or None,
            user_prompt=body.user_prompt or task.description or "",
            one_shot=one_shot,
        )
        task_svc.update(task_id, task_status="queue")

        project = project_svc.get(task.project_id)
        task = task_svc.get(task_id)
        return _enrich_task(task.to_dict(), project.path, session, project)
    finally:
        session.close()


@app.get("/api/tasks/{task_id}/runs")
async def list_task_runs(task_id: str):
    """Execution history for a task."""
    session, _, task_svc = _get_services()
    try:
        task = task_svc.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        run_svc = RunService(session)
        runs = run_svc.list_by_task(task_id)
        return [r.to_dict() for r in runs]
    finally:
        session.close()


class ResumeBody(BaseModel):
    prompt: str = ""


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: str):
    """Pause an active run -- kills agent, marks as paused (not completed)."""
    session, project_svc, task_svc = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.completed_at:
            raise HTTPException(status_code=400, detail="Run is already completed")

        task = task_svc.get(run.task_id)
        project = project_svc.get(run.project_id) if run.project_id else None
        if task and project:
            is_git = project.is_git_repo if project.is_git_repo is not None else True
            AgentService.kill_agent(
                project.path,
                task.worktree_branch if is_git else "",
                task_id="" if is_git else task.id,
            )

        run_svc.pause(run_id)
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str, body: ResumeBody):
    """Resume a paused run, optionally with an additional prompt."""
    session, _, _ = _get_services()
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
    prompt: str = ""


@app.post("/api/runs/{run_id}/retry-step")
async def retry_step(run_id: str, body: RetryStepBody):
    """Re-activate an interrupted run and re-run from a specific step."""
    session, _, _ = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.retry_step(run_id, body.step_name, prompt=body.prompt)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/step-runs/{step_run_id}/complete")
async def complete_step_manually(step_run_id: str):
    """Manually mark a step as completed so the flow can advance."""
    session, _, _ = _get_services()
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
    """Stop or dequeue a run. If not yet started, deletes the run and returns the task to backlog."""
    session, project_svc, task_svc = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.completed_at:
            raise HTTPException(status_code=400, detail="Run is already completed")

        # Queued but not yet picked up — just remove it and return task to backlog
        if not run.started_at:
            task_svc.update(run.task_id, task_status="backlog")
            session.delete(run)
            session.commit()
            return {"ok": True, "killed": False, "dequeued": True}

        # Mark cancelled BEFORE killing the agent so the daemon's next poll
        # always sees completed_at set and skips gate evaluation.
        run_svc.mark_completed(run_id, outcome="cancelled")

        task = task_svc.get(run.task_id)
        project = project_svc.get(run.project_id) if run.project_id else None
        killed = False
        if task and project:
            is_git = project.is_git_repo if project.is_git_repo is not None else True
            killed = AgentService.kill_agent(
                project.path,
                task.worktree_branch if is_git else "",
                task_id="" if is_git else task.id,
            )

        return {"ok": True, "killed": killed, "dequeued": False}
    finally:
        session.close()


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a completed or queued (not yet started) task run by ID."""
    session, _, _ = _get_services()
    try:
        from ..db.models import TaskRun
        run = session.query(TaskRun).filter_by(id=run_id).first()
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
    session, _, _ = _get_services()
    try:
        from ..db.models import TaskRun
        run = session.query(TaskRun).filter_by(id=run_id).first()
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

        # Group all step runs by step_name for retry history
        step_runs_by_name: dict[str, list] = {}
        for sr in step_runs:
            step_runs_by_name.setdefault(sr.step_name, []).append(sr)

        # Latest step run per step (most recent attempt)
        step_run_map = {}
        for name, srs in step_runs_by_name.items():
            step_run_map[name] = max(srs, key=lambda s: s.started_at or s.created_at if hasattr(s, 'created_at') else s.started_at)

        max_started_position = -1
        for sr in step_runs:
            if sr.started_at and sr.step_position > max_started_position:
                max_started_position = sr.step_position

        result = []

        # Resolve step list from snapshot (preferred) or live template
        snap_steps = []
        if run.flow_snapshot:
            try:
                snap = json.loads(run.flow_snapshot)
                snap_steps = sorted(snap.get("steps", []), key=lambda s: s.get("position", 0))
            except (json.JSONDecodeError, TypeError):
                pass

        step_sources = snap_steps or []
        if not step_sources and run.flow_name:
            # Fallback: build step list from live template
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
        project_path = Path(run.task.project.path) if run.task and run.task.project else None

        for position, step_src in enumerate(step_sources):
            step_name = step_src["name"]
            has_ifs = bool(step_src.get("ifs"))
            sr = step_run_map.get(step_name)
            attempts = [s.to_dict() for s in sorted(step_runs_by_name.get(step_name, []), key=lambda s: s.attempt or 0)]
            if sr:
                status = sr.status
                step_data = sr.to_dict()
                if sr.awaiting_user_at and not sr.completed_at and project_path:
                    try:
                        artifacts_dir = ContextService.get_artifacts_dir(
                            project_path, run.task_id, run_id,
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

        # Add summary step if present
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
    session, _, _ = _get_services()
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
    """SSE endpoint that tails the agent's NDJSON log file for a TaskRun."""
    session, _, _ = _get_services()
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
    session, _, _ = _get_services()
    try:
        aliases = session.query(AgentAlias).order_by(AgentAlias.position, AgentAlias.name).all()
        return [a.to_dict() for a in aliases]
    finally:
        session.close()


@app.post("/api/agent-aliases")
async def create_agent_alias(body: AgentAliasCreate):
    from ..db.models import AgentAlias
    session, _, _ = _get_services()
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
    session, _, _ = _get_services()
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
    session, _, _ = _get_services()
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
    """All active TaskRuns globally (executing first, then pending)."""
    session, project_svc, task_svc = _get_services()
    try:
        run_svc = RunService(session)
        runs = run_svc.list_active()
        result = []
        for r in runs:
            d = r.to_dict()
            task = task_svc.get(r.task_id)
            project = project_svc.get(r.project_id) if r.project_id else None
            d["task_name"] = task.name if task else None
            d["project_name"] = project.name if project else None
            result.append(d)
        return result
    finally:
        session.close()


@app.get("/api/projects/{project_id}/queue")
async def project_queue(project_id: str):
    """All TaskRuns for project (pending + executing), ordered."""
    session, project_svc, _ = _get_services()
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
    session, project_svc, task_svc = _get_services()
    try:
        run_svc = RunService(session)
        projects = project_svc.list_all()
        result = []
        for p in projects:
            tasks = task_svc.list_by_project(p.id)
            all_runs = run_svc.list_by_project(p.id)
            active_runs = [r for r in all_runs if r.completed_at is None]
            pending_runs = [r for r in active_runs if r.started_at is None]
            executing_runs = [r for r in active_runs if r.started_at is not None]
            recent = [r.to_dict() for r in all_runs if r.completed_at is not None][-5:]

            task_ids_with_active = {r.task_id for r in active_runs}
            task_counts = {
                "running": len(executing_runs),
                "queued": len(pending_runs),
                "idle": sum(1 for t in tasks if t.id not in task_ids_with_active),
            }

            is_git = p.is_git_repo if p.is_git_repo is not None else True

            def _agent_active(run):
                task = task_svc.get(run.task_id)
                if not task:
                    return False
                if is_git:
                    return AgentService.is_agent_running(p.path, task.worktree_branch)
                return AgentService.is_agent_running(p.path, "", task_id=task.id)

            result.append({
                "project": p.to_dict(),
                "task_counts": task_counts,
                "queue_depth": len(pending_runs),
                "active_runs": len(executing_runs),
                "executing": [
                    {
                        "run": r.to_dict(),
                        "agent_active": _agent_active(r),
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
    """Return all steps awaiting user action across all projects."""
    session, _, _ = _get_services()
    try:
        run_svc = RunService(session)
        return run_svc.list_awaiting_user()
    finally:
        session.close()


@app.post("/api/step-runs/{step_run_id}/respond")
async def respond_to_step(step_run_id: str, body: StepRespondBody):
    """User responds to an awaiting_user step (confirm manual or answer prompt)."""
    session, _, _ = _get_services()
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
    session, project_svc, _ = _get_services()
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
                    {"name": s.name, "position": s.position}
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
    session, project_svc, _ = _get_services()
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
    session, project_svc, _ = _get_services()
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
    session, _, _ = _get_services()
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
    session, project_svc, _ = _get_services()
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
    session, _, _ = _get_services()
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
    session, _, _ = _get_services()
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
    session, _, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        step = flow_svc.add_step(
            flow_id, body.name, body.content, body.position,
            gates=body.gates, ifs=body.ifs,
            agent_alias=body.agent_alias, step_type=body.step_type,
            allow_max=body.allow_max,
            max_gate_retries=body.max_gate_retries,
        )
        if not step:
            raise HTTPException(status_code=404, detail="Flow not found")
        return step.to_dict()
    finally:
        session.close()


@app.patch("/api/flows/{flow_id}/steps/{step_id}")
async def update_flow_step(flow_id: str, step_id: str, body: StepUpdate):
    session, _, _ = _get_services()
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
        step = flow_svc.update_step(step_id, **updates)
        if not step:
            raise HTTPException(status_code=404, detail="Step not found")
        return step.to_dict()
    finally:
        session.close()


@app.delete("/api/flows/{flow_id}/steps/{step_id}")
async def delete_flow_step(flow_id: str, step_id: str):
    session, _, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        if not flow_svc.remove_step(step_id):
            raise HTTPException(status_code=404, detail="Step not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/flows/{flow_id}/reorder")
async def reorder_flow_steps(flow_id: str, body: ReorderSteps):
    session, _, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        if not flow_svc.reorder_steps(flow_id, body.step_ids):
            raise HTTPException(status_code=404, detail="Flow not found")
        flow = flow_svc.get(flow_id)
        return flow.to_dict()
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
    session, _, _ = _get_services()
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
    session, _, _ = _get_services()
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
    session, _, _ = _get_services()
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
