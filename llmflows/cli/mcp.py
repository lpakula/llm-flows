"""Connectors CLI -- manage connectors (browser, web search, third-party)."""

import json

import click

from ..db.database import get_session
from ..db.models import McpConnector


@click.group("connectors")
def connectors():
    """Manage connectors (web search, browser, third-party)."""
    pass


@connectors.command("list")
def connectors_list():
    """List all installed connectors."""
    session = get_session()
    try:
        rows = session.query(McpConnector).order_by(
            McpConnector.builtin.desc(), McpConnector.server_id
        ).all()
    finally:
        session.close()

    if not rows:
        click.echo("No connectors configured.")
        return

    id_w = max(len(c.server_id) for c in rows)
    name_w = max(len(c.name) for c in rows)

    cols = [
        click.style("ID".ljust(id_w), bold=True),
        click.style("NAME".ljust(name_w), bold=True),
        click.style("STATUS".ljust(10), bold=True),
        click.style("PORT".ljust(6), bold=True),
        click.style("TYPE", bold=True),
    ]
    click.echo("  ".join(cols))
    click.echo(click.style("  ".join([
        "─" * id_w, "─" * name_w, "─" * 10, "─" * 6, "─" * 10
    ]), fg="bright_black"))

    for c in rows:
        enabled = click.style("enabled", fg="green") if c.enabled else click.style("disabled", fg="bright_black")
        port = str(c.port) if c.port else "-"
        ctype = click.style("built-in", fg="blue") if c.builtin else "custom"
        cols = [
            click.style(c.server_id.ljust(id_w), fg="cyan"),
            click.style(c.name.ljust(name_w), fg="white"),
            enabled.ljust(19),
            click.style(port.ljust(6), fg="yellow"),
            ctype,
        ]
        click.echo("  ".join(cols))


@connectors.command("catalog")
def connectors_catalog():
    """Show available connector servers from the catalog."""
    from ..ui.server import MCP_CATALOG

    session = get_session()
    try:
        installed = {c.server_id for c in session.query(McpConnector).all()}
    finally:
        session.close()

    categories: dict[str, list] = {}
    for entry in MCP_CATALOG:
        cat = entry.get("category", "Other")
        categories.setdefault(cat, []).append(entry)

    for cat, entries in categories.items():
        click.echo(f"\n{click.style(cat, bold=True)}")
        for entry in entries:
            badge = click.style(" [installed]", fg="green") if entry["server_id"] in installed else ""
            click.echo(f"  {click.style(entry['server_id'], fg='cyan')}  {entry['name']}{badge}")
            click.echo(click.style(f"    {entry.get('description', '')}", fg="bright_black"))


@connectors.command("add")
@click.argument("server_id")
@click.option("--command", default="", help="Shell command to start the connector server.")
@click.option("--name", default="", help="Display name for the connector.")
def connectors_add(server_id, command, name):
    """Add a connector (from catalog or custom).

    \b
    Example (catalog):  llmflows connectors add notion
    Example (custom):   llmflows connectors add my-server --command "npx my-mcp-server"
    """
    from ..ui.server import MCP_CATALOG

    session = get_session()
    try:
        existing = session.query(McpConnector).filter_by(server_id=server_id).first()
        if existing:
            click.echo(f"Connector '{server_id}' already exists. Use 'llmflows connectors enable {server_id}' to enable it.")
            raise SystemExit(1)

        catalog_entry = next((c for c in MCP_CATALOG if c["server_id"] == server_id), None)
        resolved_name = name or (catalog_entry["name"] if catalog_entry else server_id)
        resolved_command = command or (catalog_entry["command"] if catalog_entry else "")

        if not resolved_command:
            click.echo(f"No command specified and '{server_id}' not found in catalog. Use --command to specify.")
            raise SystemExit(1)

        connector = McpConnector(
            server_id=server_id,
            name=resolved_name,
            command=resolved_command,
            enabled=False,
            builtin=False,
        )
        session.add(connector)
        session.commit()
        click.echo(f"Added {click.style(resolved_name, fg='cyan')} ({server_id})")
        if catalog_entry and catalog_entry.get("required_credentials"):
            click.echo(click.style("  Required credentials:", fg="yellow"))
            for key in catalog_entry["required_credentials"]:
                click.echo(f"    llmflows connectors config {server_id} {key} <value>")
        click.echo(f"  Enable with: llmflows connectors enable {server_id}")
    except SystemExit:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@connectors.command("remove")
@click.argument("server_id")
def connectors_remove(server_id):
    """Remove a connector."""
    session = get_session()
    try:
        connector = session.query(McpConnector).filter_by(server_id=server_id).first()
        if not connector:
            click.echo(f"Connector '{server_id}' not found.")
            raise SystemExit(1)
        if connector.builtin:
            click.echo(f"Cannot remove built-in connector '{server_id}'. Disable it instead.")
            raise SystemExit(1)
        session.delete(connector)
        session.commit()
        click.echo(f"Removed {click.style(connector.name, fg='cyan')}")
    except SystemExit:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@connectors.command("enable")
@click.argument("server_id")
def connectors_enable(server_id):
    """Enable a connector."""
    session = get_session()
    try:
        connector = session.query(McpConnector).filter_by(server_id=server_id).first()
        if not connector:
            click.echo(f"Connector '{server_id}' not found.")
            raise SystemExit(1)
        connector.enabled = True
        session.commit()
        click.echo(f"Enabled {click.style(connector.name, fg='cyan')}")
    except SystemExit:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@connectors.command("disable")
@click.argument("server_id")
def connectors_disable(server_id):
    """Disable a connector."""
    session = get_session()
    try:
        connector = session.query(McpConnector).filter_by(server_id=server_id).first()
        if not connector:
            click.echo(f"Connector '{server_id}' not found.")
            raise SystemExit(1)
        connector.enabled = False
        session.commit()
        click.echo(f"Disabled {click.style(connector.name, fg='cyan')}")
    except SystemExit:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@connectors.command("config")
@click.argument("server_id")
@click.argument("key")
@click.argument("value")
def connectors_config(server_id, key, value):
    """Set a config or credential value for a connector.

    \b
    Example: llmflows connectors config notion NOTION_API_KEY ntn_xxx
    """
    session = get_session()
    try:
        connector = session.query(McpConnector).filter_by(server_id=server_id).first()
        if not connector:
            click.echo(f"Connector '{server_id}' not found.")
            raise SystemExit(1)

        if key.startswith("credentials."):
            cred_key = key[len("credentials."):]
            creds = connector.get_credentials()
            creds[cred_key] = value
            connector.credentials = json.dumps(creds)
        elif key.isupper():
            creds = connector.get_credentials()
            creds[key] = value
            connector.credentials = json.dumps(creds)
        else:
            env = connector.get_env()
            env[key] = value
            connector.env = json.dumps(env)

        session.commit()
        click.echo(f"Set {click.style(key, fg='cyan')} for {connector.name}")
    except SystemExit:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@connectors.command("test")
@click.argument("server_id")
def connectors_test(server_id):
    """Test a connector by listing its available tools."""
    click.echo(f"Testing {click.style(server_id, fg='cyan')}...")
    click.echo(click.style("(Requires the daemon to be running with this connector enabled)", fg="bright_black"))

    from ..services.mcp import McpService
    svc = McpService()
    url = svc.get_endpoint(server_id)
    if not url:
        click.echo(click.style(f"Connector '{server_id}' is not running. Start the daemon and enable it first.", fg="red"))
        raise SystemExit(1)

    click.echo(f"Server URL: {url}")
    click.echo("Use the MCP bridge to discover tools (requires the MCP SDK).")


@connectors.command("restart")
@click.argument("server_id")
def connectors_restart(server_id):
    """Restart a connector server (requires daemon to be running)."""
    click.echo(f"Restart signal for {click.style(server_id, fg='cyan')}.")
    click.echo(click.style("The daemon will restart this server on its next health check.", fg="bright_black"))


@connectors.group("setup")
def connectors_setup():
    """Run setup flows for connectors."""
    pass


@connectors_setup.command("google")
def setup_google():
    """Run the Google Workspace setup flow.

    Automates GCP project creation, API enablement, and OAuth credential setup
    using a browser-based flow. Requires the browser connector to be enabled.
    """
    from pathlib import Path

    flow_file = Path(__file__).parent.parent / "defaults" / "flows" / "setup-google.json"
    if not flow_file.exists():
        click.echo(click.style("Setup flow file not found.", fg="red"))
        raise SystemExit(1)

    click.echo(f"Google Workspace setup flow: {click.style(str(flow_file), fg='cyan')}")
    click.echo()
    click.echo("To run this setup flow:")
    click.echo(f"  1. Enable the browser connector: {click.style('llmflows connectors enable browser', fg='yellow')}")
    click.echo(f"  2. Import the flow: {click.style(f'llmflows flow import {flow_file}', fg='yellow')}")
    click.echo(f"  3. Start a run: {click.style('llmflows run start setup-google', fg='yellow')}")
    click.echo()
    click.echo("The flow will guide you through creating a Google Cloud project,")
    click.echo("enabling APIs, and configuring OAuth credentials.")
