"""Run CLI -- list/inspect flow runs."""

import click

from ..db.database import get_session, init_db
from ..services.flow import FlowService
from ..services.space import SpaceService
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


def _render_run_table(runs, show_space: bool = False) -> None:
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
        if show_space:
            cols.append(click.style("SPACE", bold=True))
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
        if show_space and r.space:
            last_col = r.space.name
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
@click.option("--all", "-a", "show_all", is_flag=True, help="Show runs across all spaces")
@click.option("--space", "-s", "space_id", default=None, help="Space ID")
@click.option("--limit", "-n", default=20, show_default=True, help="Max runs to show")
def run_list(show_all, space_id, limit):
    """List flow runs for a space.

    Examples:
      llmflows run list
      llmflows run list --all
      llmflows run list --space abc123
    """
    session = _get_session()
    try:
        run_svc = RunService(session)
        space_svc = SpaceService(session)

        if show_all:
            spaces = space_svc.list_all()
        elif space_id:
            p = space_svc.get(space_id)
            if not p:
                click.echo(f"Space {space_id} not found.")
                raise SystemExit(1)
            spaces = [p]
        else:
            p = space_svc.resolve_current()
            if not p:
                click.echo("Not inside a registered space. Use --all or --space <id>.")
                raise SystemExit(1)
            spaces = [p]

        all_runs = []
        for spc in spaces:
            all_runs.extend(run_svc.list_by_space(spc.id))

        all_runs.sort(key=lambda r: r.created_at or "", reverse=True)
        _render_run_table(all_runs[:limit], show_space=show_all or len(spaces) > 1)
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
        click.echo(f"Space:    {r.space.name if r.space else r.space_id}")
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
@click.option("--space", "-s", "space_id", default=None, help="Space ID")
def run_schedule(flow_id, space_id):
    """Schedule a new flow run.

    Examples:
      llmflows run schedule --flow abc123
    """
    session = _get_session()
    try:
        space_svc = SpaceService(session)
        run_svc = RunService(session)
        flow_svc = FlowService(session)

        if space_id:
            space = space_svc.get(space_id)
        else:
            space = space_svc.resolve_current()

        if not space:
            click.echo("Not inside a registered space. Use --space <id>.")
            raise SystemExit(1)

        flow = flow_svc.get(flow_id)
        if not flow:
            click.echo(f"Flow {flow_id} not found.")
            raise SystemExit(1)

        new_run = run_svc.enqueue(space.id, flow_id)
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
