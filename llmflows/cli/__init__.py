"""CLI for llmflows -- system-wide agentic workflow tool."""

import click

from .. import __version__
from .admin import register_cmd, space
from .agent import agent
from .daemon import daemon
from .flow import flow
from .mcp import connectors
from .run import run
from .skill import skill
from .ui import ui
from .upgrade import upgrade


@click.group()
@click.version_option(version=__version__, prog_name="llmflows", message="%(prog)s version %(version)s")
def cli():
    """llmflows -- agentic workflow orchestrator."""
    pass


cli.add_command(register_cmd)
cli.add_command(space)
cli.add_command(agent)
cli.add_command(daemon)
cli.add_command(flow)
cli.add_command(connectors)
cli.add_command(run)
cli.add_command(skill)
cli.add_command(ui)
cli.add_command(upgrade)
