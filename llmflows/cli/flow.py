"""Flow CLI commands -- manage flows and steps."""

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


