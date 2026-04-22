"""Flow CLI commands -- manage flows and steps."""

import json
import sys
from pathlib import Path

import click

from ..db.database import get_session, init_db
from ..services.flow import FlowService
from ..services.space import SpaceService


def _get_session():
    init_db()
    return get_session()


def _resolve_space(session):
    """Resolve the current space or exit."""
    space_svc = SpaceService(session)
    space = space_svc.resolve_current()
    if space is None:
        click.echo("Not inside a registered space. Run 'llmflows register' first.")
        raise SystemExit(1)
    return space


@click.group()
def flow():
    """Manage flows and their steps."""
    pass


@flow.command("list")
def flow_list():
    """List all flows with step counts."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        flows = flow_svc.list_by_space(space.id)
        if not flows:
            click.echo("No flows found. Run 'llmflows register' to seed defaults.")
            return

        name_w = max(len(f.name) for f in flows)
        name_w = max(name_w, 4)

        cols = [
            click.style("NAME".ljust(name_w), bold=True),
            click.style("STEPS".ljust(5), bold=True),
            click.style("DESCRIPTION", bold=True),
        ]
        click.echo("  ".join(cols))
        click.echo(click.style("  ".join(["─" * name_w, "─" * 5, "─" * 40]), fg="bright_black"))

        for f in flows:
            desc = f.description or ""
            if len(desc) > 50:
                desc = desc[:47] + "..."
            cols = [
                click.style(f.name.ljust(name_w), fg="cyan"),
                click.style(str(len(f.steps)).ljust(5), fg="yellow"),
                click.style(desc, fg="white"),
            ]
            click.echo("  ".join(cols))
    finally:
        session.close()


@flow.command("show")
@click.argument("name")
def flow_show(name):
    """Show flow details and ordered steps."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        click.echo(f"Name:        {f.name}")
        click.echo(f"Description: {f.description or '-'}")
        click.echo(f"Steps:       {len(f.steps)}")
        click.echo()
        click.secho("Steps:", bold=True)
        for s in sorted(f.steps, key=lambda s: s.position):
            preview = s.content[:60].replace("\n", " ") if s.content else "(empty)"
            click.echo(f"  {s.position}. {click.style(s.name, fg='cyan')}  {click.style(preview, fg='bright_black')}")
    finally:
        session.close()


@flow.command("create")
@click.argument("name")
@click.option("--copy-from", default=None, help="Duplicate an existing flow")
@click.option("--description", "-d", default="", help="Flow description")
def flow_create(name, copy_from, description):
    """Create a new flow (optionally duplicate an existing flow)."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        if copy_from:
            f = flow_svc.duplicate(copy_from, name, space_id=space.id)
            if not f:
                click.echo(f"Source flow '{copy_from}' not found.")
                raise SystemExit(1)
            if description:
                flow_svc.update(f.id, description=description)
        else:
            f = flow_svc.create(name=name, space_id=space.id, description=description)
        click.echo(f"Created flow {click.style(f.name, fg='cyan')} ({f.id})")
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    finally:
        session.close()


@flow.command("delete")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def flow_delete(name, yes):
    """Delete a flow (cannot delete 'default')."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        if not yes:
            click.confirm(f"Delete flow '{name}' ({len(f.steps)} steps)?", abort=True)

        flow_svc.delete(f.id)
        click.echo(f"Deleted flow '{name}'")
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    finally:
        session.close()


@flow.command("export")
@click.option("--output", "-o", default=None, help="Output file path")
def flow_export(output):
    """Export all flows to JSON."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        if output:
            flow_svc.export_flows(space.id, Path(output))
            click.echo(f"Exported to {output}")
        else:
            import json
            data = flow_svc.export_flows(space.id)
            click.echo(json.dumps(data, indent=2))
    finally:
        session.close()


@flow.command("import")
@click.argument("file", type=click.Path(exists=True))
def flow_import(file):
    """Import flows from a JSON file."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        count = flow_svc.import_flows(Path(file), space.id)
        click.echo(f"Imported {count} flow(s) from {file}")
    finally:
        session.close()


@flow.group("step")
def flow_step():
    """Manage steps within a flow."""
    pass


@flow_step.command("list")
@click.option("--flow", "flow_name", required=True, help="Flow name")
def step_list(flow_name):
    """List steps in a flow with positions."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(flow_name, space.id)
        if not f:
            click.echo(f"Flow '{flow_name}' not found.")
            raise SystemExit(1)

        for s in sorted(f.steps, key=lambda s: s.position):
            click.echo(f"  {s.position}. {click.style(s.name, fg='cyan')} ({s.id})")
    finally:
        session.close()


@flow_step.command("add")
@click.option("--flow", "flow_name", required=True, help="Flow name")
@click.option("--name", "step_name", required=True, help="Step name")
@click.option("--content", "-c", default=None, help="Content file path (reads stdin if omitted)")
@click.option("--position", "-p", type=int, default=None, help="Position in flow")
def step_add(flow_name, step_name, content, position):
    """Add a step to a flow."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(flow_name, space.id)
        if not f:
            click.echo(f"Flow '{flow_name}' not found.")
            raise SystemExit(1)

        if content:
            step_content = Path(content).read_text()
        elif not sys.stdin.isatty():
            step_content = sys.stdin.read()
        else:
            step_content = ""

        step = flow_svc.add_step(f.id, step_name, step_content, position)
        if step:
            click.echo(f"Added step {click.style(step_name, fg='cyan')} at position {step.position}")
        else:
            click.echo("Failed to add step.", err=True)
            raise SystemExit(1)
    finally:
        session.close()


@flow_step.command("edit")
@click.option("--flow", "flow_name", required=True, help="Flow name")
@click.option("--name", "step_name", required=True, help="Step name")
@click.option("--content", "-c", required=True, help="Content file path")
def step_edit(flow_name, step_name, content):
    """Update a step's content."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(flow_name, space.id)
        if not f:
            click.echo(f"Flow '{flow_name}' not found.")
            raise SystemExit(1)

        step = None
        for s in f.steps:
            if s.name == step_name:
                step = s
                break

        if not step:
            click.echo(f"Step '{step_name}' not found in flow '{flow_name}'.")
            raise SystemExit(1)

        step_content = Path(content).read_text()
        flow_svc.update_step(step.id, content=step_content)
        click.echo(f"Updated step {click.style(step_name, fg='cyan')}")
    finally:
        session.close()


@flow_step.command("remove")
@click.option("--flow", "flow_name", required=True, help="Flow name")
@click.option("--name", "step_name", required=True, help="Step name")
def step_remove(flow_name, step_name):
    """Remove a step from a flow."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(flow_name, space.id)
        if not f:
            click.echo(f"Flow '{flow_name}' not found.")
            raise SystemExit(1)

        step = None
        for s in f.steps:
            if s.name == step_name:
                step = s
                break

        if not step:
            click.echo(f"Step '{step_name}' not found in flow '{flow_name}'.")
            raise SystemExit(1)

        flow_svc.remove_step(step.id)
        click.echo(f"Removed step {click.style(step_name, fg='cyan')}")
    finally:
        session.close()


# ── flow schedule ────────────────────────────────────────────────────────────

def _compute_next_run(cron_expr: str, tz_str: str = "UTC"):
    from datetime import datetime, timezone as _tz
    from croniter import croniter
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    tz = ZoneInfo(tz_str) if tz_str != "UTC" else _tz.utc
    now_local = datetime.now(tz)
    cron = croniter(cron_expr, now_local)
    next_local = cron.get_next(datetime)
    return next_local.astimezone(_tz.utc).replace(tzinfo=None)


@flow.command("schedule")
@click.argument("name")
@click.option("--cron", default=None, help='Cron expression (e.g. "0 9 * * 1-5")')
@click.option("--timezone", "-tz", "tz", default=None, help="Timezone (default: UTC)")
@click.option("--enable", is_flag=True, default=False, help="Enable the schedule")
@click.option("--disable", is_flag=True, default=False, help="Disable the schedule")
@click.option("--clear", is_flag=True, default=False, help="Remove the schedule entirely")
def flow_schedule(name, cron, tz, enable, disable, clear):
    """View or update the schedule for a flow.

    \b
    Examples:
      llmflows flow schedule my-flow
      llmflows flow schedule my-flow --cron "0 9 * * 1-5" --timezone US/Eastern --enable
      llmflows flow schedule my-flow --disable
      llmflows flow schedule my-flow --clear
    """
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        if not cron and not tz and not enable and not disable and not clear:
            status = click.style("enabled", fg="green") if f.schedule_enabled else click.style("disabled", fg="bright_black")
            click.echo(f"Flow:     {click.style(f.name, fg='cyan')}")
            click.echo(f"Schedule: {status}")
            click.echo(f"Cron:     {f.schedule_cron or '-'}")
            click.echo(f"Timezone: {f.schedule_timezone or 'UTC'}")
            if f.schedule_next_at:
                click.echo(f"Next run: {f.schedule_next_at.isoformat()}")
            return

        if enable and disable:
            click.echo("Cannot use --enable and --disable together.")
            raise SystemExit(1)

        updates = {}

        if clear:
            updates["schedule_cron"] = None
            updates["schedule_enabled"] = False
            updates["schedule_next_at"] = None
            updates["schedule_timezone"] = None
        else:
            if cron:
                from croniter import croniter
                if not croniter.is_valid(cron):
                    click.echo(f"Invalid cron expression: {cron}")
                    raise SystemExit(1)
                updates["schedule_cron"] = cron

            if tz:
                updates["schedule_timezone"] = tz

            if disable:
                updates["schedule_enabled"] = False
                updates["schedule_next_at"] = None
            elif enable:
                effective_cron = cron or f.schedule_cron
                if not effective_cron:
                    click.echo("Cannot enable schedule without a cron expression. Use --cron.")
                    raise SystemExit(1)
                effective_tz = tz or f.schedule_timezone or "UTC"
                updates["schedule_enabled"] = True
                updates["schedule_next_at"] = _compute_next_run(effective_cron, effective_tz)
            elif cron and f.schedule_enabled:
                effective_tz = tz or f.schedule_timezone or "UTC"
                updates["schedule_next_at"] = _compute_next_run(cron, effective_tz)

        flow_svc.update(f.id, **updates)
        if clear:
            click.echo(f"Cleared schedule for {click.style(name, fg='cyan')}")
        elif disable:
            click.echo(f"Disabled schedule for {click.style(name, fg='cyan')}")
        elif enable:
            next_at = updates.get("schedule_next_at")
            click.echo(f"Enabled schedule for {click.style(name, fg='cyan')}  (next run: {next_at.isoformat() if next_at else '?'})")
        else:
            click.echo(f"Updated schedule for {click.style(name, fg='cyan')}")
    finally:
        session.close()


# ── flow tools ───────────────────────────────────────────────────────────────

@flow.group("tools")
def flow_tools():
    """Manage tool requirements for a flow."""
    pass


@flow_tools.command("list")
@click.argument("name")
def flow_tools_list(name):
    """List tools enabled for a flow."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        reqs = f.get_requirements()
        tools = reqs.get("tools", [])
        if not tools:
            click.echo(f"No tools enabled for {click.style(name, fg='cyan')}.")
            return

        click.secho(f"Tools for {name}:", bold=True)
        for t in tools:
            click.echo(f"  • {click.style(t, fg='cyan')}")
    finally:
        session.close()


@flow_tools.command("add")
@click.argument("name")
@click.argument("tool")
def flow_tools_add(name, tool):
    """Enable a tool for a flow.

    \b
    Available tools: web_search, browser
    Example: llmflows flow tools add my-flow web_search
    """
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        reqs = f.get_requirements()
        tools = reqs.get("tools", [])
        if tool in tools:
            click.echo(f"Tool '{tool}' is already enabled for {click.style(name, fg='cyan')}.")
            return

        tools.append(tool)
        reqs["tools"] = tools
        flow_svc.update(f.id, requirements=json.dumps(reqs))
        click.echo(f"Added {click.style(tool, fg='cyan')} to {click.style(name, fg='cyan')}")
    finally:
        session.close()


@flow_tools.command("remove")
@click.argument("name")
@click.argument("tool")
def flow_tools_remove(name, tool):
    """Remove a tool from a flow.

    Example: llmflows flow tools remove my-flow browser
    """
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        reqs = f.get_requirements()
        tools = reqs.get("tools", [])
        if tool not in tools:
            click.echo(f"Tool '{tool}' is not enabled for {click.style(name, fg='cyan')}.")
            return

        tools.remove(tool)
        reqs["tools"] = tools
        flow_svc.update(f.id, requirements=json.dumps(reqs))
        click.echo(f"Removed {click.style(tool, fg='cyan')} from {click.style(name, fg='cyan')}")
    finally:
        session.close()


# ── flow var ─────────────────────────────────────────────────────────────────

@flow.group("var")
def flow_var():
    """Manage flow-level variables.

    Flow variables are available as {{flow.KEY}} in step content, gates, and IFs.
    Pass --env to also inject the variable as an environment variable at agent runtime.
    """
    pass


@flow_var.command("set")
@click.argument("name")
@click.argument("key")
@click.argument("value")
@click.option("--env", "is_env", is_flag=True, default=False, help="Also inject as agent env variable")
def flow_var_set(name, key, value, is_env):
    """Set a flow variable.

    \b
    Examples:
      llmflows flow var set my-flow API_KEY sk-abc123 --env
      llmflows flow var set my-flow NOTES "for reference only"
    """
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        variables = f.get_variables()
        variables[key] = {"value": value, "is_env": is_env}
        flow_svc.update(f.id, variables=json.dumps(variables))
        env_tag = click.style(" [env]", fg="green") if is_env else ""
        click.echo(f"  {click.style(key, fg='cyan')} = {click.style(value, fg='white')}{env_tag}")
    finally:
        session.close()


@flow_var.command("list")
@click.argument("name")
def flow_var_list(name):
    """List all variables for a flow."""
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        variables = f.get_variables()
        if not variables:
            click.echo(f"  No variables set for {click.style(name, fg='cyan')}.")
            return

        key_w = max(len(k) for k in variables)
        for k, entry in sorted(variables.items()):
            val = entry["value"]
            env_tag = click.style(" [env]", fg="green") if entry.get("is_env") else ""
            click.echo(f"  {click.style(k.ljust(key_w), fg='cyan')}  {val}{env_tag}")
    finally:
        session.close()


@flow_var.command("remove")
@click.argument("name")
@click.argument("key")
def flow_var_remove(name, key):
    """Remove a flow variable.

    Example: llmflows flow var remove my-flow API_KEY
    """
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        variables = f.get_variables()
        if key not in variables:
            click.echo(f"  Variable '{key}' not found.")
            raise SystemExit(1)

        del variables[key]
        flow_svc.update(f.id, variables=json.dumps(variables))
        click.echo(f"  Removed {click.style(key, fg='cyan')}")
    finally:
        session.close()


# ── flow update ──────────────────────────────────────────────────────────────

@flow.command("update")
@click.argument("name")
@click.option("--description", "-d", default=None, help="Flow description")
@click.option("--max-spend", type=float, default=None, help="Max spend per run in USD")
@click.option("--max-concurrent-runs", type=int, default=None, help="Max concurrent runs")
@click.option("--rename", default=None, help="Rename the flow")
def flow_update(name, description, max_spend, max_concurrent_runs, rename):
    """Update flow settings.

    \b
    Examples:
      llmflows flow update my-flow --max-spend 5.0
      llmflows flow update my-flow --description "New description"
      llmflows flow update my-flow --rename new-name
    """
    session = _get_session()
    try:
        space = _resolve_space(session)
        flow_svc = FlowService(session)
        f = flow_svc.get_by_name(name, space.id)
        if not f:
            click.echo(f"Flow '{name}' not found.")
            raise SystemExit(1)

        updates = {}
        if description is not None:
            updates["description"] = description
        if max_spend is not None:
            updates["max_spend_usd"] = max_spend
        if max_concurrent_runs is not None:
            updates["max_concurrent_runs"] = max(1, max_concurrent_runs)
        if rename is not None:
            updates["name"] = rename

        if not updates:
            click.echo("Nothing to update. Use --description, --max-spend, --max-concurrent-runs, or --rename.")
            return

        flow_svc.update(f.id, **updates)
        changes = ", ".join(f"{k}={v}" for k, v in updates.items())
        click.echo(f"Updated {click.style(name, fg='cyan')}  ({changes})")
    finally:
        session.close()


