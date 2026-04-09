"""UI CLI command -- launch web UI."""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from ..config import load_system_config

FRONTEND_DIR = Path(__file__).parent.parent / "ui" / "frontend"
STATIC_DIR = Path(__file__).parent.parent / "ui" / "static"


def _ensure_frontend_built() -> bool:
    """Build the React frontend if the static directory is missing. Returns True if ready."""
    if (STATIC_DIR / "index.html").is_file():
        return True

    click.echo("  Frontend:        static files not found, attempting to build...")

    npm = shutil.which("npm")
    if not npm:
        click.echo(
            "  Frontend:        npm not found — cannot build automatically.\n"
            "\n"
            "  To fix, install Node.js and run:\n"
            "    cd " + str(FRONTEND_DIR) + "\n"
            "    npm install && npm run build\n"
            "\n"
            "  Or install Node.js so llmflows can build it for you on next start.",
            err=True,
        )
        return False

    if not FRONTEND_DIR.exists():
        click.echo(f"  Frontend:        source directory not found at {FRONTEND_DIR}", err=True)
        return False

    try:
        click.echo("  Frontend:        running npm install...")
        subprocess.run([npm, "install"], cwd=str(FRONTEND_DIR), check=True)
        click.echo("  Frontend:        running npm run build...")
        subprocess.run([npm, "run", "build"], cwd=str(FRONTEND_DIR), check=True)
        click.echo("  Frontend:        build complete.")
        return True
    except subprocess.CalledProcessError as e:
        click.echo(f"  Frontend:        build failed — {e}", err=True)
        return False


def _ensure_daemon_running() -> None:
    """Start the daemon if it is not already running (or restart if stale)."""
    from ..services.daemon import Daemon, write_pid_file, read_pid_file, remove_pid_file

    existing_pid = read_pid_file()
    if existing_pid:
        try:
            os.kill(existing_pid, 0)  # signal 0 = just check existence
            click.echo(f"  Daemon:          already running (pid {existing_pid})")
            return
        except ProcessLookupError:
            click.echo("  Daemon:          stale PID found, restarting…")
            remove_pid_file()

    log_file = os.path.expanduser("~/.llmflows/daemon.log")
    open(log_file, "w").close()

    pid = os.fork()
    if pid > 0:
        click.echo(f"  Daemon:          started (pid {pid})")
        return

    # ── child process ────────────────────────────────────────────────────────
    os.setsid()
    write_pid_file(os.getpid())
    sys.stdin.close()

    fmt = "%(asctime)s %(name)s %(message)s"
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter(fmt))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    try:
        Daemon().start()
    finally:
        remove_pid_file()
    sys.exit(0)


def _free_port(port: int) -> None:
    """Kill any process currently listening on *port*."""
    import socket
    import subprocess

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return

    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid:
                try:
                    os.kill(int(pid), 15)  # SIGTERM
                    click.echo(f"Freed port {port} (killed PID {pid})")
                except (ProcessLookupError, ValueError):
                    pass
    except FileNotFoundError:
        pass


def _run_dev_mode(host: str, port: int):
    """Start Vite dev server + FastAPI backend concurrently."""
    import signal
    import subprocess
    import threading

    if not FRONTEND_DIR.exists():
        click.echo(f"Error: frontend directory not found at {FRONTEND_DIR}", err=True)
        sys.exit(1)

    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        click.echo("Installing frontend dependencies...")
        subprocess.run(["npm", "install"], cwd=str(FRONTEND_DIR), check=True)

    vite_port = port
    api_port = port + 1
    _free_port(vite_port)
    _free_port(api_port)
    click.echo(f"llmflows UI (dev): http://{host}:{vite_port}")
    click.echo(f"  Vite dev server: :{vite_port}  (open this in browser)")
    click.echo(f"  FastAPI backend:  :{api_port}")
    _ensure_daemon_running()

    procs: list[subprocess.Popen] = []

    def shutdown(*_args):
        for p in procs:
            try:
                p.terminate()
            except OSError:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "llmflows.ui.server:app",
         "--host", host, "--port", str(api_port), "--log-level", "info"],
        cwd=os.getcwd(),
    )
    procs.append(api_proc)

    vite_env = {**os.environ, "LLMFLOWS_API_PORT": str(api_port)}
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--host", host, "--port", str(vite_port)],
        cwd=str(FRONTEND_DIR),
        env=vite_env,
    )
    procs.append(vite_proc)

    def _wait(p: subprocess.Popen):
        p.wait()
        shutdown()

    for p in procs:
        t = threading.Thread(target=_wait, args=(p,), daemon=True)
        t.start()

    signal.pause()


@click.command("ui")
@click.option("--port", default=None, type=int, help="Port (default from config)")
@click.option("--host", default=None, help="Host (default from config)")
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on code changes")
@click.option("--dev", is_flag=True, default=False, help="Dev mode: Vite HMR + FastAPI")
def ui(port, host, reload, dev):
    """Launch web UI on localhost (Ctrl+C to stop)."""
    from ..db.database import init_db

    init_db()

    config = load_system_config()
    port = port or config["ui"]["port"]
    host = host or config["ui"]["host"]

    if dev:
        _run_dev_mode(host, port)
        return

    import uvicorn

    click.echo(f"llmflows UI: http://{host}:{port}")
    if not _ensure_frontend_built():
        sys.exit(1)
    _ensure_daemon_running()
    kwargs = dict(host=host, port=port, log_level="warning")
    if reload:
        import llmflows
        kwargs["reload"] = True
        kwargs["reload_dirs"] = [str(Path(llmflows.__file__).parent)]
    uvicorn.run("llmflows.ui.server:app", **kwargs)
