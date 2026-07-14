"""UI CLI command -- launch web UI."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from ..config import load_system_config

FRONTEND_DIR = Path(__file__).parent.parent / "ui" / "frontend"
STATIC_DIR = Path(__file__).parent.parent / "ui" / "static"


def _llmflows_bin() -> str:
    """Return the ``llmflows`` entry-point from the same venv as the running interpreter.

    ``sys.prefix`` reliably points at the venv root even when
    ``sys.executable`` resolves to a framework Python on macOS.
    """
    venv_bin = Path(sys.prefix) / "bin" / "llmflows"
    if venv_bin.is_file():
        return str(venv_bin)
    import shutil
    found = shutil.which("llmflows")
    if found:
        return found
    return str(venv_bin)


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


def _kill_other_ui_instances() -> None:
    """Terminate any other ``llmflows ui`` processes owned by the current user.

    Ensures only one UI instance runs at a time. Excludes the current process.

    Skipped when ``LLMFLOWS_HOME`` is set — in that case the process is an
    intentionally isolated worktree instance that must not disturb the
    production UI (and vice-versa).
    """
    if "LLMFLOWS_HOME" in os.environ:
        return

    import subprocess
    from .daemon import _stop_pid

    try:
        out = subprocess.check_output(
            ["pgrep", "-u", str(os.getuid()), "-f", "llmflows ui"],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return

    own = os.getpid()
    own_ppid = os.getppid()
    others: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid = int(line)
        except ValueError:
            continue
        if pid in (own, own_ppid):
            continue
        others.append(pid)

    if not others:
        return

    click.echo(f"  UI:              found existing instance(s) {others}, stopping…")
    for pid in sorted(set(others)):
        _stop_pid(pid)


def _ensure_database() -> None:
    """Start bundled Postgres when DATABASE_URL is not configured."""
    from ..services.postgres import ensure_postgres

    url = ensure_postgres()
    click.echo(f"  Database:        Postgres ({url.split('@')[-1]})")


def _ensure_daemon_running() -> None:
    """Start the daemon if it is not already running (or restart if stale).

    Spawns ``llmflows daemon start`` as a detached subprocess so the daemon
    process has a recognisable cmdline (``llmflows daemon start``) and goes
    through the single canonical start path that writes the PID file.
    """
    import subprocess
    import time
    from ..services.daemon import read_pid_file, remove_pid_file

    existing_pid = read_pid_file()
    if existing_pid:
        try:
            os.kill(existing_pid, 0)
            if "LLMFLOWS_DEV_HOME" in os.environ:
                from .daemon import _stop_pid
                click.echo(f"  Daemon:          restarting for dev (pid {existing_pid})…")
                _stop_pid(existing_pid)
                remove_pid_file()
            else:
                click.echo(f"  Daemon:          already running (pid {existing_pid})")
                return
        except ProcessLookupError:
            click.echo("  Daemon:          stale PID found, restarting…")
            remove_pid_file()

    from .daemon import _find_orphan_daemon_pids, _stop_pid
    orphans = _find_orphan_daemon_pids()
    if orphans:
        click.echo(
            f"  Daemon:          found orphan llmflows daemon(s) {orphans}, "
            "stopping before starting fresh…"
        )
        for opid in orphans:
            _stop_pid(opid)

    cmd = [_llmflows_bin(), "daemon", "start"]

    env = os.environ.copy()

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )

    for _ in range(120):  # up to ~30s
        time.sleep(0.25)
        new_pid = read_pid_file()
        if new_pid:
            click.echo(f"  Daemon:          started (pid {new_pid})")
            return
    click.echo("  Daemon:          did not register a PID within 30s — check daemon.log", err=True)


def _maybe_reexec_for_dev(dev: bool) -> None:
    """Re-exec with ``LLMFLOWS_HOME`` pointing at ``<cwd>/.llmflows``.

    Module-level constants in ``config.py`` (``SYSTEM_DIR``, …)
    are frozen at import time.  The only way to redirect them for ``--dev`` is
    to set the env var *before* the Python interpreter imports the package, so
    we ``os.execve`` ourselves with the var already in the environment.

    ``LLMFLOWS_DEV_HOME`` is a sentinel that prevents an infinite re-exec loop.
    """
    if not dev:
        return
    if "LLMFLOWS_DEV_HOME" in os.environ:
        return
    dev_home = Path.cwd() / ".llmflows"
    dev_home.mkdir(parents=True, exist_ok=True)

    prod_home = Path.home() / ".llmflows"
    prod_pkg = prod_home / "package.json"
    dev_node_modules = dev_home / "node_modules"
    if prod_pkg.is_file() and not dev_node_modules.exists():
        import shutil
        import subprocess
        shutil.copy2(prod_pkg, dev_home / "package.json")
        subprocess.run(
            ["npm", "install", "--prefix", str(dev_home)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    local_bin = Path.cwd() / ".venv" / "bin" / "llmflows"
    if local_bin.is_file():
        exe = str(local_bin)
        argv = [exe, *sys.argv[1:]]
    else:
        exe = sys.executable
        argv = [exe, *sys.argv]

    env = {**os.environ, "LLMFLOWS_HOME": str(dev_home), "LLMFLOWS_DEV_HOME": str(dev_home),
           "LLMFLOWS_HOST_HOME": str(dev_home.resolve()),
           "LLMFLOWS_USER_HOME": str(Path.home())}
    os.execve(exe, argv, env)


def _auto_register_dev_space() -> None:
    """Register the CWD as a space in the dev DB if not already registered.

    In dev mode, ``block_unsafe_runs`` is disabled so flows can be
    tested without passing the security audit first.
    """
    from ..db.database import init_db, get_session
    from ..services.space import SpaceService
    from ..services.flow import FlowService

    init_db(seed=False)
    session = get_session()
    try:
        cwd = str(Path.cwd())
        space_svc = SpaceService(session)
        existing = space_svc.get_by_path(cwd)
        if existing:
            if existing.block_unsafe_runs or existing.audit_flows_on_import:
                space_svc.update(existing.id, block_unsafe_runs=False, audit_flows_on_import=False)
            click.echo(f"  Space:           {existing.name} ({cwd})")
            return
        name = Path(cwd).name
        s = space_svc.register(name=name, path=cwd)
        space_svc.update(s.id, block_unsafe_runs=False, audit_flows_on_import=False)
        dot_dir = Path(cwd) / ".llmflows"
        dot_dir.mkdir(parents=True, exist_ok=True)
        flow_svc = FlowService(session)
        flow_svc.sync_from_disk(cwd, s.id)
        click.echo(f"  Space:           registered '{name}' ({cwd})")
    finally:
        session.close()


def _find_free_port(start: int) -> int:
    """Return the first free TCP port at or above *start*."""
    import socket
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}\u2013{start + 99}")


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


def _run_dev_mode(host: str, port: int, no_daemon: bool = False, no_db: bool = False):
    """Start Vite dev server + FastAPI backend concurrently.

    Vite runs as a subprocess; uvicorn runs in the main process so
    Ctrl+C shuts everything down cleanly.
    """
    import atexit
    import signal
    import subprocess

    if not FRONTEND_DIR.exists():
        click.echo(f"Error: frontend directory not found at {FRONTEND_DIR}", err=True)
        sys.exit(1)

    click.echo("  Frontend:        checking dependencies...")
    subprocess.run(["npm", "install"], cwd=str(FRONTEND_DIR), check=True,
                   stdout=subprocess.DEVNULL)

    vite_port = _find_free_port(port + 100)
    api_port = _find_free_port(vite_port + 1)

    dev_home = os.environ.get("LLMFLOWS_HOME", "~/.llmflows")
    click.echo("llmflows UI (dev)")
    click.echo(f"  Home:            {dev_home}")
    click.echo(f"  Open:            http://{host}:{vite_port}")
    click.echo(f"  API:             http://{host}:{api_port}")

    _auto_register_dev_space()

    if not no_daemon:
        _ensure_daemon_running()

    vite_env = {**os.environ, "LLMFLOWS_API_PORT": str(api_port)}
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--host", host, "--port", str(vite_port)],
        cwd=str(FRONTEND_DIR),
        env=vite_env,
        start_new_session=True,
    )

    def _kill_vite():
        try:
            os.killpg(vite_proc.pid, signal.SIGTERM)
            vite_proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(vite_proc.pid, signal.SIGKILL)
            except OSError:
                pass

    atexit.register(_kill_vite)

    import uvicorn
    llmflows_pkg_dir = str(Path(__file__).parent.parent)
    uvicorn.run(
        "llmflows.ui.server:app",
        host=host, port=api_port, log_level="info",
        reload=True, reload_dirs=[llmflows_pkg_dir],
    )


@click.command("ui")
@click.option("--port", default=None, type=int, help="Port (default from config)")
@click.option("--host", default=None, help="Host (default from config)")
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on code changes")
@click.option("--dev", is_flag=True, default=False, help="Dev mode: Vite HMR + FastAPI")
@click.option("--no-daemon", "no_daemon", is_flag=True, default=False,
              help="Skip starting the daemon (useful for testing/screenshots).")
@click.option("--no-db", "no_db", is_flag=True, default=False,
              help="Skip starting the bundled Postgres container (DATABASE_URL must be set).")
def ui(port, host, reload, dev, no_daemon, no_db):
    """Launch web UI on localhost (Ctrl+C to stop)."""
    _maybe_reexec_for_dev(dev)

    _kill_other_ui_instances()

    if not no_db:
        try:
            _ensure_database()
        except Exception as exc:
            click.echo(f"  Database:        failed to start Postgres — {exc}", err=True)
            sys.exit(1)
    elif not os.environ.get("DATABASE_URL"):
        click.echo("  Database:        --no-db requires DATABASE_URL to be set", err=True)
        sys.exit(1)

    from ..db.database import init_db

    init_db()

    config = load_system_config()
    port = port or config["ui"]["port"]
    host = host or config["ui"]["host"]

    if dev:
        _run_dev_mode(host, port, no_daemon=no_daemon, no_db=no_db)
        return

    import uvicorn

    click.echo(f"llmflows UI: http://{host}:{port}")
    if not _ensure_frontend_built():
        sys.exit(1)
    if not no_daemon:
        _ensure_daemon_running()
    kwargs = dict(host=host, port=port, log_level="warning")
    if reload:
        import llmflows
        kwargs["reload"] = True
        kwargs["reload_dirs"] = [str(Path(llmflows.__file__).parent)]
    uvicorn.run("llmflows.ui.server:app", **kwargs)
