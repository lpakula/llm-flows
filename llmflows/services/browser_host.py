"""Host Chrome management for Docker runner containers.

Runner containers control the user's local Google Chrome via CDP
(host.docker.internal:9222). Chrome itself runs on the orchestrator host
with a persistent profile under ~/.llmflows/browser-profile.
"""

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from ..config import SYSTEM_DIR

logger = logging.getLogger("llmflows.browser_host")

CDP_PORT = 9222
CDP_VERSION_URL = f"http://127.0.0.1:{CDP_PORT}/json/version"
CHROME_PID_FILE = SYSTEM_DIR / "browser-chrome.pid"

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
]


def resolve_chrome_path() -> Optional[str]:
    for path in CHROME_PATHS:
        if Path(path).is_file():
            return path
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def expand_env_path(value: str) -> str:
    if value.startswith("~"):
        return os.path.expanduser(value)
    if "$HOME" in value:
        return value.replace("$HOME", str(Path.home()))
    return value


def default_profile_dir() -> Path:
    return SYSTEM_DIR / "browser-profile"


def browser_connector_uses_host(session) -> bool:
    """Return True when the browser connector is configured for headed/host mode.

    Default is headless Chromium inside the runner container — host Chrome is
    opt-in (``BROWSER_MODE=host`` or explicit ``BROWSER_HEADLESS=false``),
    so flows don't touch the user's machine unless asked to.
    """
    from ..db.models import McpConnector

    connector = session.query(McpConnector).filter_by(server_id="browser").first()
    if not connector or not connector.enabled:
        return False
    env = connector.get_env()
    if env.get("BROWSER_MODE", "").lower() == "host":
        return True
    return env.get("BROWSER_HEADLESS", "true").lower() != "true"


def connectors_need_host_browser(connector_ids: list[str], session) -> bool:
    """Return True when a connector list needs headed Chrome on the host."""
    if not connector_ids:
        return False
    if "browser-host" in connector_ids:
        return True
    if "browser" in connector_ids and browser_connector_uses_host(session):
        return True
    return False


def _browser_profile_dir(session) -> Path:
    profile_dir = default_profile_dir()
    from ..db.models import McpConnector

    connector = session.query(McpConnector).filter_by(server_id="browser").first()
    if connector:
        raw = connector.get_env().get("BROWSER_USER_DATA_DIR", "")
        if raw:
            profile_dir = Path(expand_env_path(str(raw)))
    return profile_dir


def prepare_host_browser_for_connectors(connector_ids: list[str], session) -> bool:
    """Ensure host Chrome is running when chat or a run needs headed browser access."""
    if not connectors_need_host_browser(connector_ids, session):
        return False

    ensure_host_chrome(_browser_profile_dir(session), headless=False, force_restart=True)
    return True


def flow_needs_host_browser(flow_snapshot: Optional[str], session) -> bool:
    """Check whether a flow run needs host Chrome (headed browser in Docker)."""
    if not flow_snapshot:
        return False
    try:
        snap = json.loads(flow_snapshot)
    except (json.JSONDecodeError, TypeError):
        return False

    uses_host_connector = browser_connector_uses_host(session)
    for step in snap.get("steps", []):
        connectors = step.get("connectors", step.get("mcp", step.get("tools", []))) or []
        if "browser-host" in connectors:
            return True
        if "browser" in connectors and uses_host_connector:
            return True
    return False


def is_cdp_available() -> bool:
    try:
        with urllib.request.urlopen(CDP_VERSION_URL, timeout=1) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _llmflows_chrome_is_running() -> bool:
    """Return True when the Chrome process llmflows spawned is still alive."""
    if not CHROME_PID_FILE.is_file():
        return False
    try:
        pid = int(CHROME_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return False
    import os
    import signal as _signal
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def ensure_host_chrome(
    profile_dir: Optional[Path] = None,
    *,
    headless: bool = False,
    force_restart: bool = False,
) -> None:
    """Start Google Chrome on the host with remote debugging if not already running."""
    if (
        not force_restart
        and is_cdp_available()
        and _llmflows_chrome_is_running()
    ):
        return

    # Restart so Chrome binds CDP on 0.0.0.0 (required for Docker runner access).
    stop_host_chrome()

    chrome = resolve_chrome_path()
    if not chrome:
        raise RuntimeError(
            "Google Chrome not found on host. Install Chrome or set BROWSER_HEADLESS=true "
            "to use in-container headless Chromium instead."
        )

    profile = profile_dir or default_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)

    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-debugging-address=0.0.0.0",
        "--no-first-run",
        "--disable-infobars",
        f"--user-data-dir={profile}",
    ]
    if headless:
        args.append("--headless=new")

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        CHROME_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        CHROME_PID_FILE.write_text(str(proc.pid))
    except OSError:
        logger.debug("Could not write Chrome pid file", exc_info=True)

    for _ in range(40):
        if is_cdp_available():
            logger.info("Host Chrome ready on port %d (profile=%s)", CDP_PORT, profile)
            return
        time.sleep(0.25)

    raise RuntimeError(f"Host Chrome did not become available on port {CDP_PORT}")


def stop_host_chrome() -> None:
    """Stop the Chrome process that llmflows itself spawned.

    Only the PID recorded at spawn time is killed — a user's own Chrome that
    happens to listen on the CDP port is never touched.
    """
    if not CHROME_PID_FILE.is_file():
        return
    try:
        pid = int(CHROME_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        CHROME_PID_FILE.unlink(missing_ok=True)
        return

    import os
    import signal as _signal
    try:
        os.kill(pid, _signal.SIGTERM)
        logger.debug("Stopped host Chrome (pid %d)", pid)
    except (ProcessLookupError, PermissionError):
        pass
    CHROME_PID_FILE.unlink(missing_ok=True)


def prepare_host_browser_for_run(flow_snapshot: Optional[str], session) -> bool:
    """Ensure host Chrome is running when a flow needs headed browser access.

    Returns True when host browser was required (caller may track lifecycle).
    """
    if not flow_needs_host_browser(flow_snapshot, session):
        return False

    ensure_host_chrome(_browser_profile_dir(session), headless=False, force_restart=True)
    return True
