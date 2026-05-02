"""Daemon CLI commands -- start/stop/status."""

import logging
import os
import signal
import subprocess
import sys
import time

import click

from ..services.daemon import Daemon, write_pid_file, read_pid_file, remove_pid_file


def _find_orphan_daemon_pids(exclude_pid: int | None = None) -> list[int]:
    """Find any running 'llmflows daemon' processes owned by current user.

    Used as a safety net when the PID file is missing (e.g. because a previous
    `daemon stop` deleted it before the process actually exited). Returns
    deduplicated PIDs sorted oldest-first; excludes ``exclude_pid`` and the
    current process.
    """
    try:
        out = subprocess.check_output(
            ["pgrep", "-u", str(os.getuid()), "-f", "llmflows daemon"],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    pids: list[int] = []
    own = os.getpid()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid = int(line)
        except ValueError:
            continue
        if pid == own or pid == exclude_pid:
            continue
        pids.append(pid)
    return sorted(set(pids))


def _stop_pid(pid: int, timeout: float = 5.0) -> bool:
    """Send SIGTERM, wait up to ``timeout`` seconds, escalate to SIGKILL.

    Returns True if the process is gone (or never existed) by the end.
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)

    click.echo(f"Daemon (pid {pid}) ignored SIGTERM, sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True

    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


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

    orphans = _find_orphan_daemon_pids()
    if orphans:
        click.echo(
            f"Found running llmflows daemon process(es) without a PID file: {orphans}. "
            "Stopping them before starting a new one.",
        )
        for pid in orphans:
            _stop_pid(pid)

    init_db()

    from ..config import SYSTEM_DIR
    log_file = str(SYSTEM_DIR / "daemon.log")
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
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)

        try:
            d = Daemon()
            d.start()
        finally:
            remove_pid_file()


@daemon.command("stop")
@click.option("--timeout", default=5.0, show_default=True,
              help="Seconds to wait for SIGTERM before escalating to SIGKILL.")
def daemon_stop(timeout):
    """Stop the llmflows daemon."""
    pid = read_pid_file()
    targets: list[int] = []
    if pid is not None:
        targets.append(pid)

    orphans = _find_orphan_daemon_pids(exclude_pid=pid)
    if orphans:
        click.echo(f"Also stopping orphan daemon process(es): {orphans}")
        targets.extend(orphans)

    if not targets:
        click.echo("Daemon is not running.")
        return

    for target in targets:
        ok = _stop_pid(target, timeout=timeout)
        if ok:
            click.echo(f"Daemon stopped (pid {target})")
        else:
            click.echo(f"Failed to stop daemon (pid {target})", err=True)
    remove_pid_file()


@daemon.command("restart")
@click.option("--timeout", default=5.0, show_default=True,
              help="Seconds to wait for SIGTERM before escalating to SIGKILL.")
@click.pass_context
def daemon_restart(ctx, timeout):
    """Stop the daemon (if running) and start a fresh one."""
    ctx.invoke(daemon_stop, timeout=timeout)
    # Give the OS a moment to release the PID and any sockets.
    time.sleep(0.3)
    ctx.invoke(daemon_start, foreground=False)


@daemon.command("status")
def daemon_status():
    """Show daemon status."""
    pid = read_pid_file()
    if pid:
        click.echo(f"Daemon is running (pid {pid})")
    else:
        click.echo("Daemon is not running.")


@daemon.command("tick")
@click.option("--verbose", "-v", is_flag=True, help="Mirror daemon logs to stdout.")
def daemon_tick(verbose):
    """Run a single daemon tick synchronously (for testing/debugging).

    Processes all pending run transitions exactly once, then exits. No PID
    file is written and no background process is started, making it safe to
    call inside a worktree or test environment without conflicting with a
    running daemon.
    """
    from ..db.database import init_db

    init_db()

    if verbose:
        import logging
        fmt = "%(asctime)s %(name)s %(message)s"
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt))
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)
        for noisy in ("httpx", "httpcore", "telegram", "telegram.ext"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    d = Daemon()
    click.echo("Running daemon tick…")
    d._tick()
    click.echo("Tick complete.")
