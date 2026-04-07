"""Task CLI commands -- CRUD for tasks from the project directory."""

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


def _get_session():
    init_db()
    return get_session()


@click.group()
def task():
    """Manage tasks for the current project."""
    pass


@task.command("create")
@click.option("-t", "--title", required=True, help="Task title")
@click.option("-d", "--description", required=True, help="Task description — used as the prompt for the first run")
@click.option("--type", "task_type", default="feature",
              type=click.Choice(["feature", "fix", "refactor", "chore"]))
def task_create(title, description, task_type):
    """Create a new task.

    Examples:
      llmflows task create -t "Fix login flow" -d "Safari shows blank page on submit"
      llmflows task create -t "Add pagination" -d "Add pagination to the list view"
    """
    session = _get_session()
    try:
        project = _resolve_project(session)
        task_svc = TaskService(session)
        t = task_svc.create(
            project_id=project.id,
            name=title,
            description=description,
            task_type=TaskType(task_type),
        )

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
@click.option("--flow", "flow_name", default=None, help="Flow to run (omit for prompt-only)")
@click.option("--prompt", "-p", default="", help="User prompt for this run")
@click.option("--one-shot", "one_shot", is_flag=True,
              help="Run all steps in a single prompt (for capable models)")
def task_start(task_id, flow_name, prompt, one_shot):
    """Enqueue a new run for a task.

    Examples:

      llmflows task start --id abc123 --flow default
      llmflows task start --id abc123 --prompt "Fix the bug"
      llmflows task start --id abc123 --flow default --one-shot
    """
    session = _get_session()
    try:
        task_svc = TaskService(session)
        t = task_svc.get(task_id)
        if not t:
            click.echo(f"Task {task_id} not found.")
            raise SystemExit(1)

        run_svc = RunService(session)
        effective_flow = flow_name or t.default_flow_name
        run = run_svc.enqueue(t.project_id, task_id,
                              flow_name=effective_flow,
                              user_prompt=prompt,
                              one_shot=one_shot)
        flow_label = click.style(effective_flow or "prompt-only", fg="bright_green")
        click.echo(
            f"Queued run {click.style(run.id[:8], fg='cyan')} "
            f"for task {click.style(task_id, fg='cyan')} "
            f"({flow_label}) — daemon will pick up shortly"
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
