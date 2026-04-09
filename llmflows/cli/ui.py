"""UI CLI command -- launch web UI."""

from pathlib import Path

import click

from ..config import load_system_config

FRONTEND_DIR = Path(__file__).parent.parent / "ui" / "frontend"


def _free_port(port: int) -> None:
    """Kill any process currently listening on *port*."""
    import signal
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
                    import os
                    os.kill(int(pid), signal.SIGTERM)
                    click.echo(f"Freed port {port} (killed PID {pid})")
                except (ProcessLookupError, ValueError):
                    pass
    except FileNotFoundError:
        pass


def _run_dev_mode(host: str, port: int):
    """Start Vite dev server + FastAPI backend concurrently."""
    import os
    import signal
    import subprocess
    import sys
    import threading

    if not FRONTEND_DIR.exists():
        click.echo(f"Error: frontend directory not found at {FRONTEND_DIR}", err=True)
        sys.exit(1)

    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        click.echo("Installing frontend dependencies...")
        subprocess.run(["npm", "install"], cwd=str(FRONTEND_DIR), check=True)

    vite_port = 5173
    _free_port(port)
    _free_port(vite_port)
    click.echo(f"llmflows UI (dev): http://{host}:{vite_port}")
    click.echo(f"  Vite dev server: :{vite_port}  (open this in browser)")
    click.echo(f"  FastAPI backend:  :{port}")

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
         "--host", host, "--port", str(port), "--log-level", "info"],
        cwd=os.getcwd(),
    )
    procs.append(api_proc)

    vite_env = {**os.environ, "LLMFLOWS_API_PORT": str(port)}
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
    kwargs = dict(host=host, port=port, log_level="warning")
    if reload:
        import llmflows
        kwargs["reload"] = True
        kwargs["reload_dirs"] = [str(Path(llmflows.__file__).parent)]
    uvicorn.run("llmflows.ui.server:app", **kwargs)
