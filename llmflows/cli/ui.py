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

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    for _ in range(40):  # up to ~10s
        time.sleep(0.25)
        new_pid = read_pid_file()
        if new_pid:
            click.echo(f"  Daemon:          started (pid {new_pid})")
            return
    click.echo("  Daemon:          did not register a PID within 10s — check daemon.log", err=True)


def _maybe_reexec_for_dev(dev: bool) -> None:
    """Re-exec with ``LLMFLOWS_HOME`` pointing at ``<cwd>/.llmflows``.

    Module-level constants in ``config.py`` (``SYSTEM_DIR``, ``SYSTEM_DB``, …)
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

    env = {**os.environ, "LLMFLOWS_HOME": str(dev_home), "LLMFLOWS_DEV_HOME": str(dev_home)}
    os.execve(exe, argv, env)


def _auto_register_dev_space() -> None:
    """Register the CWD as a space in the dev DB if not already registered."""
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
            click.echo(f"  Space:           {existing.name} ({cwd})")
            return
        name = Path(cwd).name
        s = space_svc.register(name=name, path=cwd)
        dot_dir = Path(cwd) / ".llmflows"
        dot_dir.mkdir(parents=True, exist_ok=True)
        flow_svc = FlowService(session)
        flow_svc.sync_from_disk(cwd, s.id)
        click.echo(f"  Space:           registered '{name}' ({cwd})")
    finally:
        session.close()


def _copy_prod_config_to_dev() -> None:
    """Copy the OpenAI API key and agent aliases from production into the dev DB.

    Aliases are matched by ``(type, name)`` (their unique constraint) and
    upserted so the dev DB mirrors production configuration.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from ..db.database import get_session
    from ..db.models import AgentConfig, AgentAlias

    prod_db = Path.home() / ".llmflows" / "llmflows.db"
    if not prod_db.exists():
        return

    dev_session = get_session()
    try:
        prod_engine = create_engine(f"sqlite:///{prod_db}")
        prod_session = Session(prod_engine)
        try:
            copied_key = False
            gemini = prod_session.query(AgentConfig).filter_by(agent="google", key="GEMINI_API_KEY").first()
            if gemini:
                exists = dev_session.query(AgentConfig).filter_by(agent=gemini.agent, key=gemini.key).first()
                if not exists:
                    dev_session.add(AgentConfig(agent=gemini.agent, key=gemini.key, value=gemini.value))
                    copied_key = True

            copied_aliases = 0
            for alias in prod_session.query(AgentAlias).all():
                exists = dev_session.query(AgentAlias).filter_by(type=alias.type, name=alias.name).first()
                if exists:
                    exists.agent = alias.agent
                    exists.model = alias.model
                    exists.position = alias.position
                else:
                    dev_session.add(AgentAlias(
                        name=alias.name, type=alias.type,
                        agent=alias.agent, model=alias.model,
                        position=alias.position,
                    ))
                copied_aliases += 1

            if copied_key or copied_aliases:
                dev_session.commit()
                parts = []
                if copied_key:
                    parts.append("Gemini key")
                if copied_aliases:
                    parts.append(f"{copied_aliases} alias(es)")
                click.echo(f"  Config:          copied {', '.join(parts)} from production")
        finally:
            prod_session.close()
            prod_engine.dispose()
    finally:
        dev_session.close()


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


def _run_dev_mode(host: str, port: int, no_daemon: bool = False):
    """Start Vite dev server + FastAPI backend concurrently."""
    import signal
    import subprocess
    import threading

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
    _copy_prod_config_to_dev()

    if not no_daemon:
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

    llmflows_pkg_dir = str(Path(__file__).parent.parent)
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "llmflows.ui.server:app",
         "--host", host, "--port", str(api_port), "--log-level", "info",
         "--reload", "--reload-dir", llmflows_pkg_dir],
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
    _maybe_reexec_for_dev(dev)

    from ..db.database import init_db

    _kill_other_ui_instances()
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
