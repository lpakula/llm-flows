"""Per-flow tool installation inside runner containers.

Each flow owns a tools directory inside the space mount
(``<space>/.llmflows/<flow>/tools``). The flow's ``setup_script`` installs
CLI tools, pip packages, and npm packages into it — nothing is baked into
the shared runner image and nothing touches the host system. Because the
directory lives on the space bind mount it persists across runs, and
deleting the flow's ``.llmflows`` folder removes its tools with it.

The environment exported by :func:`flow_tools_env` makes standard installers
target the tools dir:

- ``PATH`` is prefixed with ``<tools>/bin``
- ``PYTHONUSERBASE=<tools>`` → ``pip install --user <pkg>``
- ``npm_config_prefix=<tools>`` → ``npm install -g <pkg>``

Static binaries (ffmpeg, yt-dlp, …) can be downloaded straight into
``<tools>/bin``.
"""

import hashlib
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("llmflows.flow_setup")

SETUP_HASH_FILE = ".setup-hash"
SETUP_LOG_FILE = "setup.log"
DEFAULT_SETUP_TIMEOUT = 900


def flow_tools_dir(space_root: Path, flow_name: str) -> Path:
    """Tools directory for a flow, inside the space's .llmflows dir."""
    from .context import ContextService

    safe_flow = ContextService._safe_flow_dir(flow_name) if flow_name else "_default"
    return space_root / ".llmflows" / safe_flow / "tools"


def flow_tools_env(tools_dir: Path, base_env: dict | None = None) -> dict[str, str]:
    """Environment overrides that point installers and PATH at the tools dir."""
    env = dict(base_env if base_env is not None else os.environ)
    bin_dir = tools_dir / "bin"
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONUSERBASE"] = str(tools_dir)
    env["npm_config_prefix"] = str(tools_dir)
    env["LLMFLOWS_FLOW_TOOLS_DIR"] = str(tools_dir)
    return env


def apply_flow_tools_env(tools_dir: Path) -> None:
    """Apply tools-dir environment to the current process.

    Agent subprocesses and gate commands inherit the run-daemon's environment,
    so applying it once here makes flow tools available everywhere in the run.
    """
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "bin").mkdir(exist_ok=True)
    os.environ.update(flow_tools_env(tools_dir, base_env=os.environ))


def ensure_flow_setup(
    setup_script: str,
    tools_dir: Path,
    cwd: Path,
    timeout: int = DEFAULT_SETUP_TIMEOUT,
) -> tuple[bool, str]:
    """Run the flow's setup script once per script version.

    A hash of the script is stored in the tools dir; the script only re-runs
    when it changes. Output is written to ``<tools>/setup.log``.
    Returns ``(ok, error_message)``.
    """
    script = (setup_script or "").strip()
    if not script:
        return True, ""

    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "bin").mkdir(exist_ok=True)

    script_hash = hashlib.sha256(script.encode()).hexdigest()
    hash_file = tools_dir / SETUP_HASH_FILE
    if hash_file.is_file() and hash_file.read_text().strip() == script_hash:
        logger.info("Flow setup unchanged (hash %s), skipping", script_hash[:12])
        return True, ""

    log_file = tools_dir / SETUP_LOG_FILE
    logger.info("Running flow setup script into %s", tools_dir)
    try:
        with open(log_file, "w") as fh:
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=str(cwd),
                env=flow_tools_env(tools_dir),
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired:
        return False, f"Flow setup script timed out after {timeout}s (see {log_file})"
    except OSError as exc:
        return False, f"Flow setup script failed to start: {exc}"

    if result.returncode != 0:
        tail = ""
        try:
            text = log_file.read_text(errors="replace")
            tail = text[-2000:]
        except OSError:
            pass
        return False, (
            f"Flow setup script exited with code {result.returncode}.\n\n"
            f"Output tail:\n{tail}"
        )

    hash_file.write_text(script_hash)
    logger.info("Flow setup completed (hash %s)", script_hash[:12])
    return True, ""
