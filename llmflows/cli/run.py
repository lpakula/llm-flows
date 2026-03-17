"""Run CLI -- list/inspect runs and agent-facing commands."""

import click

from ..config import get_repo_root
from ..db.database import get_session, init_db
from ..services.context import ContextService
from ..services.project import ProjectService
from ..services.run import RunService


def _get_session():
    init_db()
    return get_session()


@click.group("run")
def run():
    """List and inspect task runs."""
    pass


# ── run list ────────────────────────────────────────────────────────────────

RUN_STATUS_COLORS = {
    "queued": "bright_blue",
    "running": "bright_yellow",
    "completed": "green",
}


def _render_run_table(runs, show_task: bool = False) -> None:
    if not runs:
        click.echo("No runs found.")
        return

    id_w, status_w, flow_w, step_w = 8, 9, 14, 14

    def header():
        cols = [
            click.style("RUN".ljust(id_w), bold=True),
            click.style("STATUS".ljust(status_w), bold=True),
            click.style("FLOW".ljust(flow_w), bold=True),
            click.style("STEP".ljust(step_w), bold=True),
        ]
        if show_task:
            cols.append(click.style("TASK", bold=True))
        else:
            cols.append(click.style("PROMPT", bold=True))
        return "  ".join(cols)

    def separator():
        cols = ["─" * id_w, "─" * status_w, "─" * flow_w, "─" * step_w, "─" * 30]
        return click.style("  ".join(cols), fg="bright_black")

    click.echo(header())
    click.echo(separator())

    for r in runs:
        status_fg = RUN_STATUS_COLORS.get(r.status, "bright_black")
        is_done = r.status == "completed"
        dim = "bright_black" if is_done else "white"

        step = r.current_step or ("-" if not is_done else "done")
        if len(step) > step_w:
            step = step[:step_w - 1] + "…"

        flow = r.flow_name or "-"
        if len(flow) > flow_w:
            flow = flow[:flow_w - 1] + "…"

        last_col = r.task_id if show_task else (r.user_prompt or "")
        if len(last_col) > 40:
            last_col = last_col[:37] + "..."

        cols = [
            click.style(r.id[:id_w].ljust(id_w), fg=dim),
            click.style(r.status.ljust(status_w), fg=status_fg),
            click.style(flow.ljust(flow_w), fg="cyan" if not is_done else "bright_black"),
            click.style(step.ljust(step_w), fg="bright_green" if not is_done else "bright_black"),
            click.style(last_col, fg=dim),
        ]
        click.echo("  ".join(cols))


@run.command("list")
@click.option("--task", "-t", "task_id", default=None, help="Filter by task ID")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show runs across all projects")
@click.option("--project", "-p", "project_id", default=None, help="Project ID")
@click.option("--limit", "-n", default=20, show_default=True, help="Max runs to show")
def run_list(task_id, show_all, project_id, limit):
    """List runs for a task or project.

    Examples:
      llmflows run list --task abc123
      llmflows run list
      llmflows run list --all
    """
    session = _get_session()
    try:
        run_svc = RunService(session)

        if task_id:
            runs = run_svc.list_by_task(task_id)
            _render_run_table(runs[-limit:], show_task=False)
            return

        project_svc = ProjectService(session)
        if show_all:
            projects = project_svc.list_all()
        elif project_id:
            p = project_svc.get(project_id)
            if not p:
                click.echo(f"Project {project_id} not found.")
                raise SystemExit(1)
            projects = [p]
        else:
            p = project_svc.resolve_current()
            if not p:
                click.echo("Not inside a registered project. Use --all or --project <id>.")
                raise SystemExit(1)
            projects = [p]

        all_runs = []
        for proj in projects:
            all_runs.extend(run_svc.list_by_project(proj.id))

        all_runs.sort(key=lambda r: r.created_at or "", reverse=True)
        _render_run_table(all_runs[:limit], show_task=True)
    finally:
        session.close()


# ── run show ─────────────────────────────────────────────────────────────────

@run.command("show")
@click.argument("run_id")
def run_show(run_id):
    """Show details for a specific run.

    Example: llmflows run show abc12345
    """
    session = _get_session()
    try:
        run_svc = RunService(session)
        r = run_svc.get(run_id)
        if not r:
            click.echo(f"Run {run_id} not found.")
            raise SystemExit(1)

        status_fg = RUN_STATUS_COLORS.get(r.status, "bright_black")
        click.echo(f"Run ID:   {click.style(r.id, fg='cyan')}")
        click.echo(f"Task:     {r.task_id}")
        click.echo(f"Status:   {click.style(r.status, fg=status_fg)}")
        click.echo(f"Flow:     {r.flow_name or '-'}")
        click.echo(f"Step:     {r.current_step or '-'}")
        if r.outcome:
            click.echo(f"Outcome:  {r.outcome}")
        if r.user_prompt:
            click.echo(f"\nPrompt:\n  {r.user_prompt}")
        if r.summary:
            click.echo(f"\nSummary:\n{r.summary}")
    finally:
        session.close()


# ── run logs ─────────────────────────────────────────────────────────────────

@run.command("logs")
@click.argument("run_id")
@click.option("--follow", "-f", is_flag=True, help="Follow log output in real time")
@click.option("--raw", is_flag=True, help="Output raw NDJSON")
def run_logs(run_id, follow, raw):
    """Print logs for a specific run.

    Example: llmflows run logs abc12345
             llmflows run logs abc12345 --follow
    """
    from .agent import stream_run_logs
    stream_run_logs(run_id, follow=follow, raw=raw)


# ── run complete (agent-facing) ───────────────────────────────────────────────

@run.command("complete")
@click.option("--summary", required=True, help="Execution summary text")
def run_complete(summary):
    """Save execution summary to the active TaskRun.

    Called by the agent at the end of the complete step.
    Example: llmflows run complete --summary "$(cat <<'EOF'
    ## What was done
    ...
    EOF
    )"
    """
    repo_root = get_repo_root()
    if repo_root is None:
        click.echo("Not inside a git repository.", err=True)
        raise SystemExit(1)

    context_svc = ContextService.find(repo_root)
    task_id = context_svc.get_current_task_id()
    run_id = context_svc.get_current_run_id()

    if not task_id:
        click.echo("No task_id found in .llmflows/task_id", err=True)
        raise SystemExit(1)

    init_db()
    session = get_session()
    try:
        run_svc = RunService(session)
        result = run_svc.set_summary(task_id, summary, run_id=run_id or None)
        if result:
            click.echo(f"Summary saved for run {result.id}.")
        else:
            click.echo(f"No active run found for task {task_id}.", err=True)
            raise SystemExit(1)
    finally:
        session.close()
