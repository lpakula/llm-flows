"""Daemon CLI commands -- start/stop/status."""

import logging
import os
import signal
import sys

import click

from ..services.daemon import Daemon, write_pid_file, read_pid_file, remove_pid_file


@click.group()
def daemon():
    """Manage the llmflows daemon."""
    pass


@daemon.command("start")
@click.option("--foreground", is_flag=True, help="Run in foreground (don't daemonize)")
def daemon_start(foreground):
    """Start the llmflows daemon."""
    from ..db.database import init_db

    existing_pid = read_pid_file()
    if existing_pid:
        click.echo(f"Daemon already running (pid {existing_pid})")
        return

    init_db()

    log_file = os.path.expanduser("~/.llmflows/daemon.log")
    open(log_file, "w").close()

    fmt = "%(asctime)s %(name)s %(message)s"
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=2)
    file_handler.setFormatter(logging.Formatter(fmt))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    for noisy in ("httpx", "httpcore", "telegram", "telegram.ext"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if foreground:
        # Also mirror to stdout when running in foreground
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter(fmt))
        root_logger.addHandler(stream_handler)
        write_pid_file(os.getpid())
        try:
            d = Daemon()
            d.start()
        finally:
            remove_pid_file()
    else:
        pid = os.fork()
        if pid > 0:
            click.echo(f"Daemon started (pid {pid})")
            return

        os.setsid()
        write_pid_file(os.getpid())
        sys.stdin.close()

        try:
            d = Daemon()
            d.start()
        finally:
            remove_pid_file()


@daemon.command("stop")
def daemon_stop():
    """Stop the llmflows daemon."""
    pid = read_pid_file()
    if pid is None:
        click.echo("Daemon is not running.")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Daemon stopped (pid {pid})")
    except ProcessLookupError:
        click.echo("Daemon process not found, cleaning up PID file.")
    remove_pid_file()


@daemon.command("status")
def daemon_status():
    """Show daemon status."""
    pid = read_pid_file()
    if pid:
        click.echo(f"Daemon is running (pid {pid})")
    else:
        click.echo("Daemon is not running.")
