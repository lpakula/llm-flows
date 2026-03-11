"""FastAPI server for the llmflows web UI."""

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import AGENT_REGISTRY, KNOWN_AGENTS, KNOWN_MODELS, get_github_token, load_system_config, save_system_config
from ..db.database import get_session, reset_engine
from ..db.models import Integration, TaskType
from ..services.agent import AgentService
from ..services.flow import FlowService
from ..services.github import GitHubService
from ..services.project import ProjectService
from ..services.run import RunService
from ..services.task import TaskService
from ..services.worktree import WorktreeService

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="llmflows", version="0.0.1")


# --- Pydantic models ---

class TaskCreate(BaseModel):
    title: str
    description: str = ""
    type: str = "feature"
    start: bool = False
    flow: str = "default"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


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


class StepUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    position: Optional[int] = None
    gates: Optional[list[dict]] = None


class ReorderSteps(BaseModel):
    step_ids: list[str]


class TaskStartBody(BaseModel):
    flow: str = "default"
    flow_chain: list[str] = []
    user_prompt: str = ""
    model: str = ""
    agent: str = "cursor"


class DaemonConfigBody(BaseModel):
    poll_interval_seconds: Optional[int] = None
    run_timeout_minutes: Optional[int] = None
    gate_timeout_seconds: Optional[int] = None


# --- Helpers ---

def _get_services():
    reset_engine()
    session = get_session()
    return session, ProjectService(session), TaskService(session)


def _enrich_task(task_dict: dict, project_path: str, session) -> dict:
    """Add dynamic fields from active TaskRun and run count."""
    run_svc = RunService(session)
    active_run = run_svc.get_active(task_dict["id"])
    all_runs = run_svc.list_by_task(task_dict["id"])
    task_dict["agent_active"] = AgentService.is_agent_running(
        project_path, task_dict.get("worktree_branch", ""),
    )
    task_dict["flow"] = active_run.flow_name if active_run else None
    task_dict["current_step"] = active_run.current_step if active_run else None
    task_dict["run_id"] = active_run.id if active_run else None
    task_dict["run_count"] = len(all_runs)
    branch = task_dict.get("worktree_branch", "")
    if branch:
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
    import os
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
    import os
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

    result = await asyncio.to_thread(
        subprocess.run, cmd,
        capture_output=True, text=True, timeout=10,
    )

    await asyncio.sleep(0.5)
    new_pid = read_pid_file()
    if new_pid:
        return {"ok": True, "running": True, "pid": new_pid}

    return {
        "ok": False, "running": False, "pid": None,
        "error": (result.stderr or result.stdout or "").strip()[:500],
    }


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
    aliases: Optional[dict] = None


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
        if body.aliases is not None:
            aliases = body.aliases
            if "default" not in aliases:
                aliases["default"] = project.get_aliases().get("default", {
                    "agent": "cursor", "model": "auto", "flow_chain": ["default"],
                })
            updates["aliases"] = json.dumps(aliases)
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


# --- Task endpoints ---

@app.get("/api/projects/{project_id}/tasks")
async def list_tasks(project_id: str):
    session, project_svc, task_svc = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        tasks = task_svc.list_by_project(project_id)
        return [_enrich_task(t.to_dict(), project.path, session) for t in tasks]
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
        )

        if body.start:
            run_svc = RunService(session)
            run_svc.enqueue(project_id, task.id, body.flow)

        return _enrich_task(task.to_dict(), project.path, session)
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
        if updates:
            task = task_svc.update(task_id, **updates)

        project = project_svc.get(task.project_id)
        return _enrich_task(task.to_dict(), project.path, session)
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


@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: str, body: TaskStartBody):
    """Enqueue a new run for a task."""
    session, project_svc, task_svc = _get_services()
    try:
        task = task_svc.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        run_svc = RunService(session)
        chain = body.flow_chain if body.flow_chain else [body.flow]
        run_svc.enqueue(task.project_id, task_id, flow_name=chain[0],
                        user_prompt=body.user_prompt or task.description or "",
                        flow_chain=chain,
                        model=body.model,
                        agent=body.agent)

        project = project_svc.get(task.project_id)
        task = task_svc.get(task_id)
        return _enrich_task(task.to_dict(), project.path, session)
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


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str):
    """Force-stop an active run by killing the agent process."""
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
        killed = False
        if task and project and task.worktree_branch:
            killed = AgentService.kill_agent(project.path, task.worktree_branch)

        run_svc.mark_completed(run_id, outcome="cancelled")
        return {"ok": True, "killed": killed}
    finally:
        session.close()


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a completed task run by ID."""
    session, _, _ = _get_services()
    try:
        from ..db.models import TaskRun
        run = session.query(TaskRun).filter_by(id=run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if not run.completed_at:
            raise HTTPException(status_code=400, detail="Cannot delete an active run")
        session.delete(run)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


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
        if run.log_path == "inline":
            raise HTTPException(
                status_code=404,
                detail="This run was started inline (--start). Logs are managed by the calling agent.",
            )
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
                            continue
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


@app.get("/api/history")
async def global_history(limit: int = 100, offset: int = 0):
    """All TaskRuns globally, newest first. Includes completed, running, and queued."""
    session, project_svc, task_svc = _get_services()
    try:
        from ..db.models import TaskRun
        query = (
            session.query(TaskRun)
            .order_by(TaskRun.created_at.desc())
        )
        total = query.count()
        runs = query.offset(offset).limit(limit).all()
        result = []
        for r in runs:
            d = r.to_dict()
            task = task_svc.get(r.task_id)
            project = project_svc.get(r.project_id) if r.project_id else None
            d["task_name"] = task.name if task else None
            d["project_name"] = project.name if project else None
            result.append(d)
        return {"runs": result, "total": total}
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

            result.append({
                "project": p.to_dict(),
                "task_counts": task_counts,
                "queue_depth": len(pending_runs),
                "active_runs": len(executing_runs),
                "executing": [
                    {
                        "run": r.to_dict(),
                        "agent_active": AgentService.is_agent_running(
                            p.path, task_svc.get(r.task_id).worktree_branch if task_svc.get(r.task_id) else "",
                        ),
                    }
                    for r in executing_runs
                ],
                "recent_completions": recent,
            })
        return result
    finally:
        session.close()


# --- Flow endpoints ---

@app.get("/api/flows")
async def list_flows():
    session, _, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flows = flow_svc.list_all()
        return [
            {
                "id": f.id,
                "name": f.name,
                "description": f.description,
                "step_count": len(f.steps),
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in flows
        ]
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


@app.post("/api/flows")
async def create_flow(body: FlowCreate):
    session, _, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        if body.copy_from:
            flow = flow_svc.duplicate(body.copy_from, body.name)
            if not flow:
                raise HTTPException(status_code=404, detail=f"Source flow '{body.copy_from}' not found")
            if body.description:
                flow_svc.update(flow.id, description=body.description)
        else:
            flow = flow_svc.create(
                name=body.name,
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
            flow_id, body.name, body.content, body.position, gates=body.gates,
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
            import json
            updates["gates"] = json.dumps(body.gates)
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


@app.post("/api/flows/export")
async def export_flows():
    session, _, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        data = flow_svc.export_flows()
        return JSONResponse(content=data)
    finally:
        session.close()


@app.post("/api/flows/import")
async def import_flows(file: UploadFile = File(...)):
    session, _, _ = _get_services()
    try:
        content = await file.read()
        data = json.loads(content)
        flow_svc = FlowService(session)
        count = flow_svc._import_flows_data(data, skip_existing=False)
        return {"imported": count}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    finally:
        session.close()


# --- Integration endpoints ---

class IntegrationCreate(BaseModel):
    provider: str
    config: dict = {}


class IntegrationUpdate(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[dict] = None


@app.get("/api/projects/{project_id}/integrations")
async def list_integrations(project_id: str):
    session, project_svc, _ = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        integrations = (
            session.query(Integration)
            .filter_by(project_id=project_id)
            .all()
        )
        return [i.to_dict() for i in integrations]
    finally:
        session.close()


@app.post("/api/projects/{project_id}/integrations")
async def create_integration(project_id: str, body: IntegrationCreate):
    session, project_svc, _ = _get_services()
    try:
        project = project_svc.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        integration = Integration(
            project_id=project_id,
            provider=body.provider,
            config=json.dumps(body.config),
        )
        session.add(integration)
        session.commit()
        return integration.to_dict()
    finally:
        session.close()


@app.patch("/api/integrations/{integration_id}")
async def update_integration(integration_id: str, body: IntegrationUpdate):
    session, _, _ = _get_services()
    try:
        integration = session.query(Integration).filter_by(id=integration_id).first()
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")
        if body.enabled is not None:
            integration.enabled = body.enabled
        if body.config is not None:
            integration.config = json.dumps(body.config)
        session.commit()
        return integration.to_dict()
    finally:
        session.close()


@app.delete("/api/integrations/{integration_id}")
async def delete_integration(integration_id: str):
    session, _, _ = _get_services()
    try:
        integration = session.query(Integration).filter_by(id=integration_id).first()
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")
        session.delete(integration)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/integrations/{integration_id}/detect-repo")
async def detect_repo(integration_id: str):
    session, project_svc, _ = _get_services()
    try:
        integration = session.query(Integration).filter_by(id=integration_id).first()
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")
        project = project_svc.get(integration.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        repo = GitHubService.get_repo_from_remote(project.path)
        if not repo:
            raise HTTPException(status_code=400, detail="Could not detect GitHub repo from git remote")
        config = integration.get_config()
        config["repo"] = repo
        integration.config = json.dumps(config)
        session.commit()
        return {"repo": repo, "integration": integration.to_dict()}
    finally:
        session.close()


# --- GitHub config ---

@app.get("/api/github/status")
async def github_status():
    token = get_github_token()
    return {"available": token is not None}


class GitHubTokenBody(BaseModel):
    token: str


@app.patch("/api/config/github")
async def update_github_config(body: GitHubTokenBody):
    config = load_system_config()
    if "github" not in config:
        config["github"] = {}
    config["github"]["token"] = body.token
    save_system_config(config)
    return {"ok": True}


@app.get("/api/config/github")
async def get_github_config():
    config = load_system_config()
    token = config.get("github", {}).get("token", "")
    has_token = bool(token)
    masked = token[:4] + "..." + token[-4:] if len(token) > 8 else ("****" if token else "")
    return {"has_token": has_token, "masked_token": masked}


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



@app.get("/api/models")
async def list_models(agent: Optional[str] = None):
    """Return models for a specific agent, or all models if no agent specified."""
    if agent and agent in AGENT_REGISTRY:
        return AGENT_REGISTRY[agent]["models"]
    return KNOWN_MODELS


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
