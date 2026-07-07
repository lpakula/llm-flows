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
    import sys
    from ..services.container import build_image, image_name

    image_tag = tag or image_name()
    click.echo(f"Building image {image_tag}…")
    ok = build_image(image_tag, no_cache=no_cache)
    sys.exit(0 if ok else 1)


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
