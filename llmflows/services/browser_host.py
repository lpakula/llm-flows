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
    """Return True when the browser connector is configured for headed/host mode."""
    from ..db.models import McpConnector

    connector = session.query(McpConnector).filter_by(server_id="browser").first()
    if not connector or not connector.enabled:
        return False
    env = connector.get_env()
    if env.get("BROWSER_MODE", "").lower() == "host":
        return True
    return env.get("BROWSER_HEADLESS", "false").lower() != "true"


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


def ensure_host_chrome(
    profile_dir: Optional[Path] = None,
    *,
    headless: bool = False,
) -> None:
    """Start Google Chrome on the host with remote debugging if not already running."""
    if is_cdp_available():
        return

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
        "--no-first-run",
        "--disable-infobars",
        f"--user-data-dir={profile}",
    ]
    if headless:
        args.append("--headless=new")

    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    for _ in range(40):
        if is_cdp_available():
            logger.info("Host Chrome ready on port %d (profile=%s)", CDP_PORT, profile)
            return
        time.sleep(0.25)

    raise RuntimeError(f"Host Chrome did not become available on port {CDP_PORT}")


def stop_host_chrome() -> None:
    """Kill the Chrome process listening on the CDP port."""
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{CDP_PORT}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return

    for pid in out.splitlines():
        pid = pid.strip()
        if pid:
            subprocess.call(["kill", pid], stderr=subprocess.DEVNULL)
    if out:
        logger.debug("Stopped host Chrome (pids: %s)", out.replace("\n", ", "))


def prepare_host_browser_for_run(flow_snapshot: Optional[str], session) -> bool:
    """Ensure host Chrome is running when a flow needs headed browser access.

    Returns True when host browser was required (caller may track lifecycle).
    """
    if not flow_needs_host_browser(flow_snapshot, session):
        return False

    profile_dir = default_profile_dir()
    from ..db.models import McpConnector

    connector = session.query(McpConnector).filter_by(server_id="browser").first()
    if connector:
        raw = connector.get_env().get("BROWSER_USER_DATA_DIR", "")
        if raw:
            profile_dir = Path(expand_env_path(str(raw)))

    ensure_host_chrome(profile_dir, headless=False)
    return True
