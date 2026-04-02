"""CLI for llmflows -- system-wide agentic workflow tool."""

import click

from .. import __version__
from .admin import register_cmd, db, project
from .agent import agent
from .alias import alias
from .daemon import daemon
from .flow import flow
from .run import run
from .task import task
from .ui import ui


@click.group()
@click.version_option(version=__version__, prog_name="llmflows", message="%(prog)s version %(version)s")
def cli():
    """llmflows -- agentic workflow orchestrator."""
    pass


cli.add_command(register_cmd)
cli.add_command(db)
cli.add_command(project)
cli.add_command(agent)
cli.add_command(alias)
cli.add_command(daemon)
cli.add_command(flow)
cli.add_command(run)
cli.add_command(task)
cli.add_command(ui)
