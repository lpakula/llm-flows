"""Browser service -- manages a browser server per run.

The daemon calls ensure_browser() when a step needs browser tools.
A detached Node.js process (browser-server.ts) launches Chrome and
prints a WebSocket endpoint.  Each step's Pi extension connects to
that endpoint, so the browser session persists across steps within a run.

Uses system Chrome with a persistent profile in ~/.llmflows/browser-profile/
to avoid the automation fingerprints of Playwright's bundled Chromium that
cause sites like Google to block login.

Node dependencies (playwright, tsx) live in ~/.llmflows/node_modules/
and are resolved via NODE_PATH at runtime.
"""

import logging
import os
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("llmflows.browser")

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
BROWSER_SERVER_SCRIPT = _TOOLS_DIR / "browser-server.ts"
_LLMFLOWS_DIR = Path.home() / ".llmflows"
_NODE_MODULES = _LLMFLOWS_DIR / "node_modules"
_DEFAULT_PROFILE_DIR = str(_LLMFLOWS_DIR / "browser-profile")
_WS_READY_TIMEOUT = 30  # seconds to wait for the WS_ENDPOINT line

_CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]


def find_chrome() -> Optional[str]:
    """Return the path to the Chrome executable, or None if not found."""
    for p in _CHROME_PATHS:
        if os.path.isfile(p):
            return p
    if binary := shutil.which("google-chrome"):
        return binary
    return None


@dataclass
class _BrowserInstance:
    proc: subprocess.Popen
    ws_endpoint: str
    pid: int


class BrowserService:
    """Manages one browser server process per run_id."""

    def __init__(self) -> None:
        self._instances: dict[str, _BrowserInstance] = {}
        self._lock = threading.Lock()

    def ensure_browser(
        self,
        run_id: str,
        headless: bool = True,
        user_data_dir: str = _DEFAULT_PROFILE_DIR,
    ) -> str:
        """Start a browser server if not already running for this run.

        Returns the WebSocket endpoint URL.
        """
        with self._lock:
            inst = self._instances.get(run_id)
            if inst and inst.proc.poll() is None:
                return inst.ws_endpoint

            if inst:
                del self._instances[run_id]

        ws = self._launch(run_id, headless, user_data_dir)
        return ws

    def get_ws_endpoint(self, run_id: str) -> Optional[str]:
        """Return the WS endpoint for a run, or None if no browser is running."""
        with self._lock:
            inst = self._instances.get(run_id)
            if inst and inst.proc.poll() is None:
                return inst.ws_endpoint
            return None

    def cleanup(self, run_id: str) -> None:
        """Kill the browser server for a given run."""
        with self._lock:
            inst = self._instances.pop(run_id, None)
        if inst:
            self._kill(inst, run_id)

    def cleanup_all(self) -> None:
        """Kill all browser servers (daemon shutdown)."""
        with self._lock:
            instances = list(self._instances.items())
            self._instances.clear()
        for run_id, inst in instances:
            self._kill(inst, run_id)

    @staticmethod
    def _check_deps() -> None:
        """Verify Chrome, tsx, and playwright are available before launch."""
        if not find_chrome():
            raise RuntimeError(
                "Browser tool requires Google Chrome but it was not found.\n"
                f"  Searched: {', '.join(_CHROME_PATHS)}\n"
                "  Install from: https://google.com/chrome\n"
                "  Then restart the daemon to enable browser tools."
            )

        tsx_bin = _NODE_MODULES / ".bin" / "tsx"
        if not tsx_bin.is_file():
            raise RuntimeError(
                "tsx not found in ~/.llmflows/node_modules/.bin/. "
                "Run: npm install --prefix ~/.llmflows playwright @sinclair/typebox tsx"
            )
        pw_dir = _NODE_MODULES / "playwright"
        if not pw_dir.is_dir():
            raise RuntimeError(
                "Playwright not found in ~/.llmflows/node_modules/. "
                "Run: npm install --prefix ~/.llmflows playwright"
            )

    def _launch(
        self,
        run_id: str,
        headless: bool,
        user_data_dir: str = _DEFAULT_PROFILE_DIR,
    ) -> str:
        """Launch browser-server.ts and wait for the WS_ENDPOINT line."""
        self._check_deps()

        env = {
            **os.environ,
            "BROWSER_HEADLESS": str(headless).lower(),
            "NODE_PATH": str(_NODE_MODULES),
        }
        if user_data_dir:
            resolved = os.path.expanduser(user_data_dir)
            os.makedirs(resolved, exist_ok=True)
            env["BROWSER_USER_DATA_DIR"] = resolved

        tsx_bin = _NODE_MODULES / ".bin" / "tsx"
        cmd = [str(tsx_bin), str(BROWSER_SERVER_SCRIPT)]

        logger.info("Launching browser server for run %s (headless=%s)", run_id, headless)

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )

        ws_endpoint = self._read_ws_endpoint(proc, run_id)

        inst = _BrowserInstance(proc=proc, ws_endpoint=ws_endpoint, pid=proc.pid)
        with self._lock:
            self._instances[run_id] = inst

        logger.info(
            "Browser server started for run %s (pid=%d, ws=%s)",
            run_id, proc.pid, ws_endpoint,
        )
        return ws_endpoint

    @staticmethod
    def _read_ws_endpoint(proc: subprocess.Popen, run_id: str) -> str:
        """Read lines from stdout until we find the WS_ENDPOINT marker."""
        import select

        deadline = __import__("time").time() + _WS_READY_TIMEOUT

        while __import__("time").time() < deadline:
            if proc.poll() is not None:
                stderr = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
                raise RuntimeError(
                    f"Browser server exited (code={proc.returncode}) for run {run_id}: {stderr}"
                )

            if proc.stdout is None:
                raise RuntimeError("Browser server stdout is None")

            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                continue

            line = proc.stdout.readline().decode(errors="replace").strip()
            if line.startswith("WS_ENDPOINT:"):
                return line[len("WS_ENDPOINT:"):]

        proc.kill()
        raise RuntimeError(
            f"Browser server did not produce WS_ENDPOINT within {_WS_READY_TIMEOUT}s for run {run_id}"
        )

    @staticmethod
    def _kill(inst: _BrowserInstance, run_id: str) -> None:
        """Terminate a browser server process."""
        try:
            os.killpg(os.getpgid(inst.pid), signal.SIGTERM)
            inst.proc.wait(timeout=5)
            logger.info("Browser server stopped for run %s (pid=%d)", run_id, inst.pid)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(inst.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            logger.warning("Browser server killed (SIGKILL) for run %s (pid=%d)", run_id, inst.pid)
        except Exception:
            logger.exception("Error stopping browser server for run %s", run_id)
