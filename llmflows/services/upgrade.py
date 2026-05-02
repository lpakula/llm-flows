"""Upgrade service — pull latest llmflows, restart daemon and UI."""

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("llmflows.upgrade")


def _pip_executable() -> str:
    return str(Path(sys.prefix) / "bin" / "pip")


def _llmflows_bin() -> str:
    venv_bin = Path(sys.prefix) / "bin" / "llmflows"
    if venv_bin.is_file():
        return str(venv_bin)
    import shutil
    return shutil.which("llmflows") or str(venv_bin)


def pip_upgrade() -> tuple[bool, str, str, str]:
    """Upgrade llmflows via pip.

    Returns ``(success, old_version, new_version, output)``.
    """
    from .. import __version__ as old_version

    pip = _pip_executable()
    try:
        result = subprocess.run(
            [pip, "install", "--upgrade", "llmflows"],
            capture_output=True, text=True, timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        return False, old_version, old_version, "pip install timed out after 120s"
    except Exception as e:
        return False, old_version, old_version, str(e)

    new_version = _get_installed_version(pip, old_version)
    return success, old_version, new_version, output


def _get_installed_version(pip: str, fallback: str) -> str:
    try:
        r = subprocess.run([pip, "show", "llmflows"], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith("Version:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return fallback


def kill_ui_processes() -> list[int]:
    """Kill any running ``llmflows ui`` processes (excludes self). Returns killed PIDs."""
    killed: list[int] = []
    try:
        out = subprocess.check_output(
            ["pgrep", "-u", str(os.getuid()), "-f", "llmflows ui"],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return killed

    own = os.getpid()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid = int(line)
        except ValueError:
            continue
        if pid == own:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except ProcessLookupError:
            pass
    return killed


def start_ui_background(no_daemon: bool = False) -> int | None:
    """Start ``llmflows ui`` as a detached background process.

    Returns the PID of the new process, or None on failure.
    """
    cmd = [_llmflows_bin(), "ui"]
    if no_daemon:
        cmd.append("--no-daemon")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid
    except Exception:
        logger.exception("Failed to start UI in background")
        return None


def restart_daemon_via_cli() -> tuple[bool, str]:
    """Stop and start the daemon (for CLI use). Returns ``(success, message)``."""
    import time

    llmflows = _llmflows_bin()

    try:
        subprocess.run(
            [llmflows, "daemon", "stop"],
            capture_output=True, timeout=15,
        )
    except Exception:
        pass

    time.sleep(0.5)

    try:
        result = subprocess.run(
            [llmflows, "daemon", "start"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def trigger_daemon_reexec() -> None:
    """Send SIGUSR2 to the current process to trigger daemon re-exec."""
    os.kill(os.getpid(), signal.SIGUSR2)
