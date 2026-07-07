"""CLI commands for Docker container runtime."""

import click


@click.group()
def runner():
    """Manage the llmflows Docker runtime."""
    pass


@runner.command("build")
@click.option("--tag", default=None, help="Custom image tag (default: llmflows:<version>)")
@click.option("--no-cache", is_flag=True, help="Build without Docker cache")
def build(tag, no_cache):
    """Build the llmflows Docker image."""
    import subprocess
    import sys
    from .. import __version__

    image_tag = tag or f"llmflows:{__version__}"
    cmd = ["docker", "build", "-t", image_tag, "."]
    if no_cache:
        cmd.insert(2, "--no-cache")

    click.echo(f"Building image {image_tag}...")
    result = subprocess.run(cmd, cwd=str(_find_project_root()))
    sys.exit(result.returncode)


@click.command("run-daemon")
@click.option("--run-id", required=True, help="Flow run ID to execute")
def run_daemon_cmd(run_id):
    """Execute a single flow run to completion (used inside containers)."""
    import logging
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from ..db.database import init_db
    from ..services.run_daemon import RunDaemon
    from ..utils.node_modules import ensure_runner_node_modules

    init_db()
    ensure_runner_node_modules()
    daemon = RunDaemon(run_id)
    exit_code = daemon.run()
    sys.exit(exit_code)


def _find_project_root():
    """Find the llmflows project root (where Dockerfile lives)."""
    from pathlib import Path

    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "Dockerfile").exists():
            return current
        current = current.parent
    return Path.cwd()
