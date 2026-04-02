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

        over_w = 9
        cols = [
            click.style("NAME".ljust(name_w), bold=True),
            click.style("AGENT".ljust(agent_w), bold=True),
            click.style("MODEL".ljust(model_w), bold=True),
            click.style("OVERRIDES".ljust(over_w), bold=True),
            click.style("FLOW CHAIN", bold=True),
        ]
        click.echo("  ".join(cols))
        click.echo(click.style("  ".join(["─" * name_w, "─" * agent_w, "─" * model_w, "─" * over_w, "─" * 30]), fg="bright_black"))

        sorted_names = sorted(aliases.keys(), key=lambda n: (n != "default", n))
        for name in sorted_names:
            cfg = aliases[name]
            chain = " → ".join(cfg.get("flow_chain", []))
            override_count = len(cfg.get("step_overrides", {}))
            override_str = str(override_count) if override_count else "-"
            name_color = "blue" if name == "default" else "cyan"
            cols = [
                click.style(name.ljust(name_w), fg=name_color),
                click.style(cfg.get("agent", "").ljust(agent_w), fg="white"),
                click.style(cfg.get("model", "").ljust(model_w), fg="white"),
                click.style(override_str.ljust(over_w), fg="yellow" if override_count else "white"),
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

        overrides = cfg.get("step_overrides", {})
        if overrides:
            click.echo(f"\nStep overrides:")
            for key in sorted(overrides):
                o = overrides[key]
                parts = []
                if o.get("agent"):
                    parts.append(f"agent={o['agent']}")
                if o.get("model"):
                    parts.append(f"model={o['model']}")
                click.echo(f"  {click.style(key, fg='yellow')}  {', '.join(parts)}")
    finally:
        session.close()


@alias.command("set")
@click.argument("name")
@click.option("--agent", "-a", default=None, help="Agent name")
@click.option("--model", "-m", default=None, help="Model name")
@click.option("--flow", "-f", "flow_chain", default=None, help="Comma-separated flow chain (e.g. default,review)")
@click.option("--step-override", "-s", "step_overrides", multiple=True,
              help="Per-step agent/model: flow/step:agent:model (repeatable)")
@click.option("--clear-overrides", is_flag=True, help="Remove all step overrides")
@click.option("--project", "project_id", default=None, help="Project ID (defaults to current repo)")
def alias_set(name, agent, model, flow_chain, step_overrides, clear_overrides, project_id):
    """Create or update an alias.

    Examples:

    \b
      llmflows alias set fast --agent cursor --model sonnet-4.6 --flow default
      llmflows alias set thorough -m sonnet-4.6-thinking -f react-js,submit-pr
      llmflows alias set default -m sonnet-4.6-thinking
      llmflows alias set default -s "default/research:claude-code:sonnet"
      llmflows alias set default -s "default/validate:claude-code:haiku"
    """
    if not agent and not model and not flow_chain and not step_overrides and not clear_overrides:
        click.echo("Provide at least one of --agent, --model, --flow, --step-override, or --clear-overrides.")
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

        if clear_overrides:
            existing.pop("step_overrides", None)

        if step_overrides:
            so = existing.get("step_overrides", {})
            for entry in step_overrides:
                parts = entry.split(":")
                if len(parts) < 2:
                    click.echo(f"Invalid step-override format: '{entry}'. Use flow/step:agent:model", err=True)
                    raise SystemExit(1)
                key = parts[0]
                entry_agent = parts[1] if len(parts) > 1 and parts[1] else None
                entry_model = parts[2] if len(parts) > 2 and parts[2] else None
                cfg = {}
                if entry_agent:
                    cfg["agent"] = entry_agent
                if entry_model:
                    cfg["model"] = entry_model
                if cfg:
                    so[key] = cfg
                else:
                    so.pop(key, None)
            existing["step_overrides"] = so

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
        so = existing.get("step_overrides", {})
        if so:
            click.echo(f"  Step overrides:")
            for key in sorted(so):
                o = so[key]
                parts = []
                if o.get("agent"):
                    parts.append(f"agent={o['agent']}")
                if o.get("model"):
                    parts.append(f"model={o['model']}")
                click.echo(f"    {key}: {', '.join(parts)}")
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
