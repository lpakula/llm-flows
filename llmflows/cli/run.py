"""Run CLI -- list/inspect flow runs."""

import click

from ..db.database import get_session, init_db
from ..services.flow import FlowService
from ..services.project import ProjectService
from ..services.run import RunService


def _get_session():
    init_db()
    return get_session()


@click.group("run")
def run():
    """List and inspect flow runs."""
    pass


# ── run list ────────────────────────────────────────────────────────────────

RUN_STATUS_COLORS = {
    "queued": "bright_blue",
    "running": "bright_yellow",
    "completed": "green",
    "interrupted": "red",
    "timeout": "red",
    "error": "red",
}


def _render_run_table(runs, show_project: bool = False) -> None:
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
        if show_project:
            cols.append(click.style("PROJECT", bold=True))
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

        last_col = ""
        if show_project and r.project:
            last_col = r.project.name
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
@click.option("--all", "-a", "show_all", is_flag=True, help="Show runs across all projects")
@click.option("--project", "-p", "project_id", default=None, help="Project ID")
@click.option("--limit", "-n", default=20, show_default=True, help="Max runs to show")
def run_list(show_all, project_id, limit):
    """List flow runs for a project.

    Examples:
      llmflows run list
      llmflows run list --all
      llmflows run list --project abc123
    """
    session = _get_session()
    try:
        run_svc = RunService(session)
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
        _render_run_table(all_runs[:limit], show_project=show_all or len(projects) > 1)
    finally:
        session.close()


# ── run show ─────────────────────────────────────────────────────────────────

@run.command("show")
@click.argument("run_id")
def run_show(run_id):
    """Show details for a specific flow run.

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
        click.echo(f"Project:  {r.project.name if r.project else r.project_id}")
        click.echo(f"Status:   {click.style(r.status, fg=status_fg)}")
        click.echo(f"Flow:     {r.flow_name or '-'}")
        click.echo(f"Step:     {r.current_step or '-'}")
        if r.outcome:
            click.echo(f"Outcome:  {r.outcome}")
        if r.summary:
            click.echo(f"\nSummary:\n{r.summary}")
    finally:
        session.close()


# ── run schedule ─────────────────────────────────────────────────────────────

@run.command("schedule")
@click.option("--flow", "-f", "flow_id", required=True, help="Flow ID to run")
@click.option("--one-shot", "one_shot", is_flag=True,
              help="Run all steps in a single prompt (for capable models)")
@click.option("--project", "-p", "project_id", default=None, help="Project ID")
def run_schedule(flow_id, one_shot, project_id):
    """Schedule a new flow run.

    Examples:
      llmflows run schedule --flow abc123
      llmflows run schedule --flow abc123 --one-shot
    """
    session = _get_session()
    try:
        project_svc = ProjectService(session)
        run_svc = RunService(session)
        flow_svc = FlowService(session)

        if project_id:
            project = project_svc.get(project_id)
        else:
            project = project_svc.resolve_current()

        if not project:
            click.echo("Not inside a registered project. Use --project <id>.")
            raise SystemExit(1)

        flow = flow_svc.get(flow_id)
        if not flow:
            click.echo(f"Flow {flow_id} not found.")
            raise SystemExit(1)

        if one_shot and flow_svc.has_human_steps(flow.name, project_id=project.id):
            click.echo(
                click.style("Warning: ", fg="yellow")
                + f"flow '{flow.name}' contains manual/prompt steps — ignoring --one-shot"
            )
            one_shot = False

        new_run = run_svc.enqueue(project.id, flow_id, one_shot=one_shot)
        click.echo(
            f"Scheduled run {click.style(new_run.id, fg='cyan')} "
            f"for flow {click.style(flow.name, fg='bright_green')} "
            f"— daemon will pick up shortly"
        )
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
