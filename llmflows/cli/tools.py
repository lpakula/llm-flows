"""Tools CLI -- manage globally available tools."""

import click

from ..config import load_system_config, save_system_config


TOOL_REGISTRY = [
    {"id": "web_search", "name": "Web Search"},
    {"id": "browser", "name": "Browser"},
]


@click.group("tools")
def tools():
    """Manage globally available tools (web search, browser)."""
    pass


@tools.command("list")
def tools_list():
    """List all available tools and their status."""
    config = load_system_config()

    name_w = max(len(t["name"]) for t in TOOL_REGISTRY)
    id_w = max(len(t["id"]) for t in TOOL_REGISTRY)

    cols = [
        click.style("ID".ljust(id_w), bold=True),
        click.style("NAME".ljust(name_w), bold=True),
        click.style("STATUS", bold=True),
    ]
    click.echo("  ".join(cols))
    click.echo(click.style("  ".join(["─" * id_w, "─" * name_w, "─" * 10]), fg="bright_black"))

    for t in TOOL_REGISTRY:
        stored = config.get(t["id"], {})
        enabled = stored.get("enabled", False)
        status = click.style("enabled", fg="green") if enabled else click.style("disabled", fg="bright_black")
        cols = [
            click.style(t["id"].ljust(id_w), fg="cyan"),
            click.style(t["name"].ljust(name_w), fg="white"),
            status,
        ]
        click.echo("  ".join(cols))


@tools.command("enable")
@click.argument("tool_id")
def tools_enable(tool_id):
    """Enable a tool globally.

    \b
    Example: llmflows tools enable web_search
    """
    tool = next((t for t in TOOL_REGISTRY if t["id"] == tool_id), None)
    if not tool:
        click.echo(f"Unknown tool '{tool_id}'. Available: {', '.join(t['id'] for t in TOOL_REGISTRY)}")
        raise SystemExit(1)

    config = load_system_config()
    if tool_id not in config:
        config[tool_id] = {}
    config[tool_id]["enabled"] = True
    save_system_config(config)
    click.echo(f"Enabled {click.style(tool['name'], fg='cyan')}")


@tools.command("disable")
@click.argument("tool_id")
def tools_disable(tool_id):
    """Disable a tool globally.

    Example: llmflows tools disable browser
    """
    tool = next((t for t in TOOL_REGISTRY if t["id"] == tool_id), None)
    if not tool:
        click.echo(f"Unknown tool '{tool_id}'. Available: {', '.join(t['id'] for t in TOOL_REGISTRY)}")
        raise SystemExit(1)

    config = load_system_config()
    if tool_id not in config:
        config[tool_id] = {}
    config[tool_id]["enabled"] = False
    save_system_config(config)
    click.echo(f"Disabled {click.style(tool['name'], fg='cyan')}")
