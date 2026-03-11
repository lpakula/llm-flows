"""Alias CLI commands -- manage project configuration aliases."""

import json

import click

from ..db.database import get_session, init_db
from ..services.project import ProjectService


def _get_session():
    init_db()
    return get_session()


def _resolve_project(session, project_id):
    project_svc = ProjectService(session)
    if project_id:
        p = project_svc.get(project_id)
    else:
        p = project_svc.resolve_current()
    if not p:
        msg = f"Project '{project_id}' not found." if project_id else "Not inside a registered project. Use --project to specify."
        click.echo(msg)
        raise SystemExit(1)
    return p, project_svc


@click.group()
def alias():
    """Manage project aliases (configuration presets)."""
    pass


@alias.command("list")
@click.option("--project", "project_id", default=None, help="Project ID (defaults to current repo)")
def alias_list(project_id):
    """List all aliases for a project."""
    session = _get_session()
    try:
        project, _ = _resolve_project(session, project_id)
        aliases = project.get_aliases()
        if not aliases:
            click.echo("No aliases configured.")
            return

        name_w = max(len(n) for n in aliases)
        name_w = max(name_w, 5)
        agent_w = max((len(c.get("agent", "")) for c in aliases.values()), default=5)
        agent_w = max(agent_w, 5)
        model_w = max((len(c.get("model", "")) for c in aliases.values()), default=5)
        model_w = max(model_w, 5)

        cols = [
            click.style("NAME".ljust(name_w), bold=True),
            click.style("AGENT".ljust(agent_w), bold=True),
            click.style("MODEL".ljust(model_w), bold=True),
            click.style("FLOW CHAIN", bold=True),
        ]
        click.echo("  ".join(cols))
        click.echo(click.style("  ".join(["─" * name_w, "─" * agent_w, "─" * model_w, "─" * 30]), fg="bright_black"))

        sorted_names = sorted(aliases.keys(), key=lambda n: (n != "default", n))
        for name in sorted_names:
            cfg = aliases[name]
            chain = " → ".join(cfg.get("flow_chain", []))
            name_color = "blue" if name == "default" else "cyan"
            cols = [
                click.style(name.ljust(name_w), fg=name_color),
                click.style(cfg.get("agent", "").ljust(agent_w), fg="white"),
                click.style(cfg.get("model", "").ljust(model_w), fg="white"),
                click.style(chain, fg="white"),
            ]
            click.echo("  ".join(cols))
    finally:
        session.close()


@alias.command("show")
@click.argument("name")
@click.option("--project", "project_id", default=None, help="Project ID (defaults to current repo)")
def alias_show(name, project_id):
    """Show details of a specific alias."""
    session = _get_session()
    try:
        project, _ = _resolve_project(session, project_id)
        cfg = project.get_alias(name)
        if not cfg:
            available = ", ".join(project.get_aliases().keys())
            click.echo(f"Alias '{name}' not found. Available: {available}")
            raise SystemExit(1)

        click.echo(f"Alias:      {click.style(name, fg='cyan')}")
        click.echo(f"Agent:      {cfg.get('agent', '-')}")
        click.echo(f"Model:      {cfg.get('model', '-')}")
        click.echo(f"Flow chain: {' → '.join(cfg.get('flow_chain', []))}")
    finally:
        session.close()


@alias.command("set")
@click.argument("name")
@click.option("--agent", "-a", default=None, help="Agent name")
@click.option("--model", "-m", default=None, help="Model name")
@click.option("--flow", "-f", "flow_chain", default=None, help="Comma-separated flow chain (e.g. default,review)")
@click.option("--project", "project_id", default=None, help="Project ID (defaults to current repo)")
def alias_set(name, agent, model, flow_chain, project_id):
    """Create or update an alias.

    Examples:

    \b
      llmflows alias set fast --agent cursor --model sonnet-4.6 --flow default
      llmflows alias set thorough -m sonnet-4.6-thinking -f react-js,submit-pr
      llmflows alias set default -m sonnet-4.6-thinking
    """
    if not agent and not model and not flow_chain:
        click.echo("Provide at least one of --agent, --model, or --flow.")
        raise SystemExit(1)

    session = _get_session()
    try:
        project, project_svc = _resolve_project(session, project_id)
        aliases = project.get_aliases()

        existing = aliases.get(name, {})
        if agent:
            existing["agent"] = agent
        if model:
            existing["model"] = model
        if flow_chain:
            existing["flow_chain"] = [f.strip() for f in flow_chain.split(",") if f.strip()]

        existing.setdefault("agent", "cursor")
        existing.setdefault("model", "auto")
        existing.setdefault("flow_chain", ["default"])

        aliases[name] = existing
        project_svc.update(project.id, aliases=json.dumps(aliases))

        action = "Updated" if name in project.get_aliases() else "Created"
        click.echo(f"{action} alias {click.style(name, fg='cyan')}")
        click.echo(f"  Agent: {existing['agent']}")
        click.echo(f"  Model: {existing['model']}")
        click.echo(f"  Flow:  {' → '.join(existing['flow_chain'])}")
    finally:
        session.close()


@alias.command("delete")
@click.argument("name")
@click.option("--project", "project_id", default=None, help="Project ID (defaults to current repo)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def alias_delete(name, project_id, yes):
    """Delete an alias (cannot delete 'default')."""
    if name == "default":
        click.echo("Cannot delete the 'default' alias. Use 'alias set default' to modify it.")
        raise SystemExit(1)

    session = _get_session()
    try:
        project, project_svc = _resolve_project(session, project_id)
        aliases = project.get_aliases()

        if name not in aliases:
            click.echo(f"Alias '{name}' not found.")
            raise SystemExit(1)

        if not yes:
            click.confirm(f"Delete alias '{name}'?", abort=True)

        del aliases[name]
        project_svc.update(project.id, aliases=json.dumps(aliases))
        click.echo(f"Deleted alias {click.style(name, fg='cyan')}")
    finally:
        session.close()
