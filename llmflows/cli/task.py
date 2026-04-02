"""Task CLI commands -- CRUD for tasks from the project directory."""

from pathlib import Path

import click

from ..db.database import get_session, init_db
from ..db.models import TaskType
from ..services.project import ProjectService
from ..services.run import RunService
from ..services.task import TaskService


def _resolve_project(session):
    """Resolve the current project or exit."""
    project_svc = ProjectService(session)
    project = project_svc.resolve_current()
    if project is None:
        click.echo("Not inside a registered project. Run 'llmflows register' first.")
        raise SystemExit(1)
    return project


def _resolve_or_register(session):
    """Resolve the current project, auto-registering if needed."""
    from ..config import get_repo_root
    project_svc = ProjectService(session)
    project = project_svc.resolve_current()
    if project:
        return project

    repo_root = get_repo_root()
    project_root = repo_root or Path.cwd()
    git_repo = repo_root is not None

    project = project_svc.register(
        name=project_root.name,
        path=str(project_root),
        git_repo=git_repo,
    )

    project_dir = project_root / ".llmflows"
    project_dir.mkdir(parents=True, exist_ok=True)

    if git_repo:
        from .admin import _update_gitignore
        _update_gitignore(project_root)

    return project


def _get_session():
    init_db()
    return get_session()


def _start_inline(session, project, task, flow_name, no_git,
                  flow_chain=None, user_prompt="",
                  model="", agent="cursor"):
    """Bootstrap an inline run — renders the first step prompt to stdout.

    Creates the run, sets up the working directory, and outputs the
    first step's prompt for the calling agent. The daemon handles
    subsequent steps.
    """
    from ..services.agent import AgentService
    from ..services.context import ContextService
    from ..services.flow import FlowService
    from ..services.worktree import WorktreeService

    run_svc = RunService(session)
    task_svc = TaskService(session)
    flow_svc = FlowService(session)

    alias_cfg = project.get_alias("default") or {}
    step_overrides = alias_cfg.get("step_overrides", {})

    run = run_svc.enqueue(project.id, task.id, flow_name,
                          user_prompt=user_prompt, flow_chain=flow_chain,
                          model=model, agent=agent,
                          step_overrides=step_overrides)
    run_svc.mark_started(run.id)

    worktree_path = None
    if no_git:
        work_dir = Path(project.path)
    else:
        branch = f"task-{task.id}"
        task_svc.update(task.id, worktree_branch=branch)
        wt_svc = WorktreeService(project.path)
        ok, msg = wt_svc.create(branch)
        if not ok:
            click.echo(f"Failed to create worktree: {msg}", err=True)
            raise SystemExit(1)
        work_dir = wt_svc.get_worktree_path(branch) or Path(project.path)
        worktree_path = str(work_dir)

    llmflows_dir = work_dir / ".llmflows"
    llmflows_dir.mkdir(parents=True, exist_ok=True)
    AgentService._ensure_gitignore(llmflows_dir)

    steps = flow_svc.get_flow_steps(flow_name)
    if not steps:
        click.echo(f"Flow '{flow_name}' has no steps.", err=True)
        raise SystemExit(1)

    first_step = steps[0]
    step_obj = flow_svc.get_step_obj(flow_name, first_step)
    step_content = (step_obj.content or "").rstrip() if step_obj else ""

    artifacts_dir = ContextService.get_artifacts_dir(Path(project.path), task.id, run.id)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    step_output_dir = artifacts_dir / f"00-{first_step}"

    context_svc = ContextService(llmflows_dir)
    prompt = context_svc.render_step_instructions({
        "worktree_path": worktree_path,
        "task_id": task.id,
        "task_description": task.description,
        "user_prompt": user_prompt or task.description,
        "step_name": first_step,
        "step_content": step_content,
        "flow_name": flow_name,
        "artifacts": [],
        "artifacts_output_dir": str(step_output_dir),
        "gate_failures": None,
    })

    override_key = f"{flow_name}/{first_step}"
    step_cfg = step_overrides.get(override_key, {})
    resolved_agent = step_cfg.get("agent") or agent
    resolved_model = step_cfg.get("model") or model

    step_run = run_svc.create_step_run(
        run_id=run.id,
        step_name=first_step,
        step_position=0,
        flow_name=flow_name,
        agent=resolved_agent,
        model=resolved_model,
    )
    run_svc.update_run_step(run.id, first_step, flow_name)
    run_svc.set_step_prompt(step_run.id, prompt)
    run_svc.set_step_log_path(step_run.id, "inline")

    click.echo(prompt)


@click.group()
def task():
    """Manage tasks for the current project."""
    pass


@task.command("create")
@click.option("-t", "--title", required=True, help="Task title")
@click.option("-d", "--description", required=True, help="Task description — used as the prompt for the first run")
@click.option("--type", "task_type", default="feature",
              type=click.Choice(["feature", "fix", "refactor", "chore"]))
@click.option("--inline", "inline_now", is_flag=True,
              help="Start the run immediately (inline, no daemon)")
@click.option("--flow", "flow_name", default="default", help="Flow to use (default: default)")
@click.option("--no-git", "no_git", is_flag=True,
              help="Run in the current directory instead of creating a git worktree")
@click.option("--model", "-m", default="", help="Model to use for this run (inline only)")
@click.option("--agent", "-a", default="cursor", help="Agent backend: cursor, claude-code, codex (inline only)")
def task_create(title, description, task_type, inline_now, flow_name, no_git, model, agent):
    """Create a new task.

    Examples:
      llmflows task create -t "Fix login flow" -d "Safari shows blank page on submit"
      llmflows task create -t "Add pagination" --inline --flow default
      llmflows task create -t "Refactor API" --inline --no-git
      llmflows task create -t "Fix bug" --inline --model gemini-3-flash --agent cursor
    """
    session = _get_session()
    try:
        project = _resolve_or_register(session) if inline_now else _resolve_project(session)
        task_svc = TaskService(session)
        t = task_svc.create(
            project_id=project.id,
            name=title,
            description=description,
            task_type=TaskType(task_type),
        )

        if inline_now:
            _start_inline(session, project, t, flow_name, no_git,
                          model=model, agent=agent)
            return

        click.echo(f"Created {click.style(t.id, fg='cyan')} — {click.style(title, fg='green', bold=True)}")
        click.echo(f"   Type:  {t.type.value}")
    finally:
        session.close()


def _render_task_table(rows: list[dict]) -> None:
    """Render a list of task dicts as a colored table."""
    if not rows:
        click.echo("No tasks found.")
        return

    has_project = any(r.get("project") for r in rows)

    id_w, type_w, status_w, runs_w, proj_w, title_w = 6, 8, 10, 4, 0, 40
    if has_project:
        proj_w = max(len(r.get("project", "")) for r in rows)
        proj_w = max(proj_w, 7)

    status_colors = {
        "new": "white",
        "queued": "bright_blue",
        "running": "bright_yellow",
        "completed": "green",
        "failed": "red",
        "cancelled": "red",
        "timeout": "bright_red",
    }

    def header():
        cols = [
            click.style("ID".ljust(id_w), bold=True),
            click.style("TYPE".ljust(type_w), bold=True),
            click.style("STATUS".ljust(status_w), bold=True),
            click.style("RUNS".ljust(runs_w), bold=True),
        ]
        if has_project:
            cols.append(click.style("PROJECT".ljust(proj_w), bold=True))
        cols.append(click.style("TITLE", bold=True))
        return "  ".join(cols)

    def separator():
        cols = ["─" * id_w, "─" * type_w, "─" * status_w, "─" * runs_w]
        if has_project:
            cols.append("─" * proj_w)
        cols.append("─" * title_w)
        return click.style("  ".join(cols), fg="bright_black")

    click.echo(header())
    click.echo(separator())

    for r in rows:
        title = r["title"] or "Untitled"
        if len(title) > 55:
            title = title[:52] + "..."

        status = r["status"]
        status_fg = status_colors.get(status, "white")

        cols = [
            click.style(r["id"].ljust(id_w), fg="magenta"),
            click.style(r["type"].ljust(type_w), fg={"feature": "cyan", "fix": "red", "refactor": "magenta", "chore": "white"}.get(r["type"], "white")),
            click.style(status.ljust(status_w), fg=status_fg),
            click.style(str(r["run_count"]).ljust(runs_w), fg="yellow"),
        ]
        if has_project:
            cols.append(click.style(r.get("project", "").ljust(proj_w), fg="cyan"))
        cols.append(click.style(title, fg="white", bold=r["has_active"]))
        click.echo("  ".join(cols))


def _tasks_to_rows(tasks, session, project_name: str = "") -> list[dict]:
    run_svc = RunService(session)
    rows = []
    for t in tasks:
        active_run = run_svc.get_active(t.id)
        all_runs = run_svc.list_by_task(t.id)
        run_count = len(all_runs)
        has_active = active_run is not None

        if has_active:
            status = active_run.status
        elif all_runs:
            latest = all_runs[0]
            status = latest.outcome if latest.outcome and latest.outcome != "completed" else latest.status
        else:
            status = "new"

        rows.append({
            "id": t.id,
            "type": t.type.value,
            "run_count": run_count,
            "has_active": has_active,
            "status": status,
            "title": t.name,
            "project": project_name,
            "sort_key": (
                not has_active,
                -t.created_at.timestamp(),
            ),
        })
    return rows


@task.command("list")
@click.option("--all", "-a", "show_all", is_flag=True,
              help="List tasks across all projects")
@click.option("--project", "-p", "project_id", default=None,
              help="Project ID (use outside a project directory)")
def task_list(show_all, project_id):
    """List tasks for the current project.

    Use --all to list tasks across all projects, or --project to target
    a specific project by ID from anywhere.
    """
    session = _get_session()
    try:
        project_svc = ProjectService(session)
        task_svc = TaskService(session)

        if show_all:
            projects = project_svc.list_all()
        elif project_id:
            proj = project_svc.get(project_id)
            if not proj:
                click.echo(f"Project {project_id} not found.")
                raise SystemExit(1)
            projects = [proj]
        else:
            current = project_svc.resolve_current()
            if not current:
                click.echo("Not inside a registered project. Use --all or --project <id>.")
                raise SystemExit(1)
            projects = [current]

        rows = []
        for proj in projects:
            tasks = task_svc.list_by_project(proj.id)
            proj_name = proj.name if show_all else ""
            rows.extend(_tasks_to_rows(tasks, session, proj_name))

        rows.sort(key=lambda r: r["sort_key"])
        _render_task_table(rows)
    finally:
        session.close()


@task.command("show")
@click.option("--id", "task_id", required=True, help="Task ID")
def task_show(task_id):
    """Show task details and run history."""
    session = _get_session()
    try:
        task_svc = TaskService(session)
        run_svc = RunService(session)
        t = task_svc.get(task_id)
        if not t:
            click.echo(f"Task {task_id} not found.")
            raise SystemExit(1)

        click.echo(f"ID:       {click.style(t.id, fg='cyan')}")
        click.echo(f"Title:    {click.style(t.name or '-', bold=True)}")
        click.echo(f"Type:     {t.type.value}")
        if t.worktree_branch:
            click.echo(f"Branch:   {t.worktree_branch}")
        click.echo(f"Created:  {t.created_at:%Y-%m-%d %H:%M}")
        if t.description:
            click.echo(f"\n{t.description}")

        runs = run_svc.list_by_task(task_id)
        if runs:
            click.echo(f"\n{click.style('RUNS', bold=True)}  ({len(runs)})")
            click.echo(click.style("  " + "─" * 60, fg="bright_black"))
            for r in runs:
                status_color = {"queued": "bright_blue", "running": "bright_yellow",
                                "completed": "green", "interrupted": "red",
                                "timeout": "red", "error": "red"}.get(r.status, "bright_black")
                step = r.current_step or ("-" if r.status != "completed" else "done")
                click.echo(
                    f"  {click.style(r.id[:8], fg='bright_black')}  "
                    f"{click.style(r.status.ljust(9), fg=status_color)}  "
                    f"{click.style(r.flow_name.ljust(12), fg='cyan')}  "
                    f"step={step}"
                )
                if r.summary:
                    preview = r.summary[:120].replace("\n", " ")
                    if len(r.summary) > 120:
                        preview += "..."
                    click.echo(f"    {click.style(preview, fg='bright_black')}")
    finally:
        session.close()


@task.command("start")
@click.option("--id", "task_id", required=True, help="Task ID")
@click.option("--flow", "flows", multiple=True, help="Flow to run (repeat to chain, e.g. --flow default --flow submit-pr)")
@click.option("--prompt", "-p", default="", help="User prompt for this run")
@click.option("--inline", "inline_now", is_flag=True,
              help="Start the run immediately (inline, no daemon)")
@click.option("--no-git", "no_git", is_flag=True,
              help="Run in the current directory instead of creating a git worktree")
@click.option("--model", "-m", default="", help="Model to use for this run")
@click.option("--agent", "-a", default="cursor", help="Agent backend: cursor, claude-code, codex")
def task_start(task_id, flows, prompt, inline_now, no_git, model, agent):
    """Enqueue a new run for a task.

    Pass --flow once for a single flow, or repeat it to chain multiple flows
    executed in order:

      llmflows task start --id abc123 --flow default
      llmflows task start --id abc123 --flow ripper-5 --flow submit-pr

    Use --inline to run inline without the daemon:

      llmflows task start --id abc123 --inline
      llmflows task start --id abc123 --inline --no-git

    Specify model and agent:

      llmflows task start --id abc123 --model gemini-3-flash --agent cursor
    """
    chain = list(flows) or ["default"]
    session = _get_session()
    try:
        task_svc = TaskService(session)
        t = task_svc.get(task_id)
        if not t:
            click.echo(f"Task {task_id} not found.")
            raise SystemExit(1)

        if inline_now:
            project_svc = ProjectService(session)
            project = project_svc.get(t.project_id)
            if not project:
                click.echo(f"Project {t.project_id} not found.", err=True)
                raise SystemExit(1)
            _start_inline(session, project, t, chain[0], no_git,
                          flow_chain=chain, user_prompt=prompt,
                          model=model, agent=agent)
            return

        run_svc = RunService(session)
        project_svc = ProjectService(session)
        project = project_svc.get(t.project_id)
        alias_cfg = (project.get_alias("default") or {}) if project else {}
        step_overrides = alias_cfg.get("step_overrides", {})
        run = run_svc.enqueue(t.project_id, task_id, chain[0],
                              user_prompt=prompt, flow_chain=chain,
                              model=model, agent=agent,
                              step_overrides=step_overrides)
        chain_str = " → ".join(click.style(f, fg="bright_green") for f in chain)
        click.echo(
            f"Queued run {click.style(run.id[:8], fg='cyan')} "
            f"for task {click.style(task_id, fg='cyan')} "
            f"({chain_str}) — daemon will pick up shortly"
        )
    finally:
        session.close()



@task.command("update")
@click.option("--id", "task_id", required=True, help="Task ID")
@click.option("--description", "-d", default=None, help="Update description")
@click.option("--title", "-t", default=None, help="New title")
def task_update(task_id, description, title):
    """Update a task.

    Example: llmflows task update --id abc123 -t "Better title"
    """
    session = _get_session()
    try:
        task_svc = TaskService(session)
        t = task_svc.get(task_id)
        if not t:
            click.echo(f"Task {task_id} not found.")
            raise SystemExit(1)

        updates = {}
        if title is not None:
            updates["name"] = title
        if description is not None:
            updates["description"] = description
        if updates:
            task_svc.update(task_id, **updates)

        t = task_svc.get(task_id)
        click.echo(f"Updated {click.style(t.id, fg='cyan')}  {t.name}")
    finally:
        session.close()


@task.command("delete")
@click.option("--id", "task_id", required=True, help="Task ID")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def task_delete(task_id, yes):
    """Delete a task and all its runs."""
    session = _get_session()
    try:
        task_svc = TaskService(session)
        t = task_svc.get(task_id)
        if not t:
            click.echo(f"Task {task_id} not found.")
            raise SystemExit(1)

        if not yes:
            click.confirm(f"Delete task '{t.name}' ({t.id})?", abort=True)

        task_svc.delete(task_id)
        click.echo(f"Deleted {task_id}")
    finally:
        session.close()
