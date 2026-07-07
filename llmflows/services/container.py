"""Container lifecycle management for the orchestrator daemon.

Handles launching, monitoring, and cleaning up runner containers.
Each flow run gets its own container running `llmflows run-daemon --run-id <id>`.
"""

import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .. import __version__
from ..config import SYSTEM_DIR
from ..db.database import get_session
from ..db.models import AgentConfig
from .network import get_network_args
from .browser_host import flow_needs_host_browser, prepare_host_browser_for_run
from .google_host import flow_google_connectors, google_oauth_volume_args, youtube_port_args

logger = logging.getLogger("llmflows.container")

_GITHUB_REPO = "lpakula/llm-flows"
_BUILD_CACHE_DIR = SYSTEM_DIR / "docker-build"


def image_name() -> str:
    """Docker image tag for runner/chat containers (matches release version)."""
    return os.environ.get("LLMFLOWS_IMAGE") or f"llmflows:{__version__}"


def find_project_root() -> Optional[Path]:
    """Find a local checkout root that contains a Dockerfile (editable installs)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "Dockerfile").is_file():
            return current
        current = current.parent
    return None


def _release_tag(version: str) -> Optional[str]:
    if not version or version == "unknown":
        return None
    return version if version.startswith("v") else f"v{version}"


def fetch_release_source(version: str | None = None) -> Optional[Path]:
    """Download the GitHub release source tree for docker build (pip installs).

    Cached under ``~/.llmflows/docker-build/<tag>/``.
    """
    tag = _release_tag(version or __version__)
    if not tag:
        return None

    cached = _BUILD_CACHE_DIR / tag
    if (cached / "Dockerfile").is_file():
        return cached

    url = f"https://github.com/{_GITHUB_REPO}/archive/refs/tags/{tag}.tar.gz"
    _BUILD_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(dir=_BUILD_CACHE_DIR) as tmp:
            archive = Path(tmp) / "source.tar.gz"
            logger.info("Downloading release source %s from GitHub", tag)
            urllib.request.urlretrieve(url, archive)

            with tarfile.open(archive, "r:gz") as tar:
                top_levels = {m.name.split("/")[0] for m in tar.getmembers() if m.name}
                if len(top_levels) != 1:
                    logger.error("Unexpected archive layout for %s", tag)
                    return None
                tar.extractall(path=tmp)

            extracted = Path(tmp) / next(iter(top_levels))
            if not (extracted / "Dockerfile").is_file():
                logger.error("Dockerfile missing in downloaded release %s", tag)
                return None

            if cached.exists():
                shutil.rmtree(cached)
            shutil.move(str(extracted), str(cached))
            return cached
    except Exception as exc:
        logger.error("Failed to download release source %s: %s", tag, exc)
        return None


def resolve_build_context() -> Optional[Path]:
    """Return a directory suitable for ``docker build`` (contains Dockerfile)."""
    source = os.environ.get("LLMFLOWS_SOURCE")
    if source:
        root = Path(source).expanduser().resolve()
        if (root / "Dockerfile").is_file():
            return root
        logger.error("LLMFLOWS_SOURCE=%s has no Dockerfile", root)

    local = find_project_root()
    if local:
        return local

    staged = stage_package_build_context()
    if staged:
        return staged

    return fetch_release_source()


def stage_package_build_context() -> Optional[Path]:
    """Stage a docker build context from the installed pip package.

    The wheel bundles ``llmflows/docker/`` (generated at pack time from root
    ``Dockerfile``, ``pyproject.toml``, ``uv.lock``, etc.).  This copies them
    plus the installed package tree into
    ``~/.llmflows/docker-build/pkg/<version>/``.
    """
    import llmflows

    pkg_root = Path(llmflows.__file__).resolve().parent
    docker_bundle = pkg_root / "docker"
    if not (docker_bundle / "Dockerfile").is_file():
        return None

    _sync_docker_bundle_from_repo(docker_bundle)

    required = (
        "Dockerfile",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "tools/package.json",
        "scripts/build.py",
    )
    for name in required:
        if not (docker_bundle / name).is_file():
            logger.error("Docker bundle incomplete — missing %s", name)
            return None

    staging = _BUILD_CACHE_DIR / "pkg" / __version__
    if (staging / ".ready").is_file() and (staging / "Dockerfile").is_file():
        return staging

    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        shutil.copy2(docker_bundle / "Dockerfile", staging / "Dockerfile")
        shutil.copy2(docker_bundle / "pyproject.toml", staging / "pyproject.toml")
        shutil.copy2(docker_bundle / "uv.lock", staging / "uv.lock")
        shutil.copy2(docker_bundle / "README.md", staging / "README.md")
        shutil.copytree(docker_bundle / "tools", staging / "tools")
        shutil.copytree(docker_bundle / "scripts", staging / "scripts")
        shutil.copytree(
            pkg_root,
            staging / "llmflows",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (staging / ".ready").touch()
        return staging
    except OSError as exc:
        logger.error("Failed to stage docker build context: %s", exc)
        return None


def _sync_docker_bundle_from_repo(docker_bundle: Path) -> None:
    """Fill docker bundle files from a local repo checkout (editable installs)."""
    local = find_project_root()
    if not local:
        return
    mappings = {
        local / "Dockerfile": docker_bundle / "Dockerfile",
        local / "pyproject.toml": docker_bundle / "pyproject.toml",
        local / "uv.lock": docker_bundle / "uv.lock",
        local / "README.md": docker_bundle / "README.md",
        local / "tools" / "package.json": docker_bundle / "tools" / "package.json",
        local / "scripts" / "build.py": docker_bundle / "scripts" / "build.py",
    }
    for src, dest in mappings.items():
        if src.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def image_exists(name: str) -> bool:
    """Return True if a Docker image with this tag is present locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _frontend_build_arg(root: Path) -> str:
    """Skip npm build when committed static UI is present in the build context."""
    static = root / "llmflows" / "ui" / "static" / "index.html"
    return "0" if static.is_file() else "1"


def build_image(
    tag: str | None = None,
    *,
    no_cache: bool = False,
) -> bool:
    """Build the llmflows Docker image. Returns True on success."""
    tag = tag or image_name()
    root = resolve_build_context()
    if not root:
        logger.error(
            "No Docker build context for %s — clone %s or set LLMFLOWS_SOURCE",
            tag,
            f"https://github.com/{_GITHUB_REPO}",
        )
        return False

    cmd = [
        "docker",
        "build",
        "-t",
        tag,
        "--build-arg",
        f"BUILD_FRONTEND={_frontend_build_arg(root)}",
        ".",
    ]
    if no_cache:
        cmd.insert(2, "--no-cache")

    logger.info("Building Docker image %s from %s", tag, root)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(root),
            timeout=1800,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-20:]
            for line in tail:
                logger.error("%s", line)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ensure_image(
    *,
    on_status: Optional[Callable[[str], None]] = None,
    quiet: bool = False,
) -> bool:
    """Ensure the runner Docker image exists, building it when missing.

    Skipped inside runner containers (``LLMFLOWS_RUNNER=1``).
    When ``quiet`` is True, only errors are reported via ``on_status``.
    """
    if os.environ.get("LLMFLOWS_RUNNER"):
        return True

    tag = image_name()
    if image_exists(tag):
        return True

    if not shutil.which("docker"):
        err = "Docker CLI not found — install Docker or build the image manually"
        if on_status:
            on_status(err)
        else:
            logger.error(err)
        return False

    if on_status and not quiet:
        on_status(f"building {tag} (first run, may take several minutes)…")
    elif not quiet:
        logger.info("Building Docker image %s", tag)

    if build_image(tag):
        if not quiet:
            logger.info("Docker image %s ready", tag)
        return True

    err = (
        f"failed to build {tag} — clone https://github.com/{_GITHUB_REPO}, "
        f"checkout {_release_tag(__version__) or 'the release tag'}, "
        "and run: llmflows runner build"
    )
    if on_status:
        on_status(err)
    else:
        logger.error(err)
    return False


def dev_volume_args() -> list[str]:
    """Bind-mount project source in dev mode so containers pick up code changes."""
    dev_home = os.environ.get("LLMFLOWS_DEV_HOME")
    if not dev_home:
        return []
    project_root = Path(dev_home).resolve().parent
    llmflows_pkg = project_root / "llmflows"
    if not llmflows_pkg.is_dir():
        return []
    args = ["-v", f"{llmflows_pkg}:/opt/llmflows/llmflows"]
    tools_pkg = project_root / "tools" / "package.json"
    if tools_pkg.is_file():
        # Overlay package.json only — keeps image node_modules, picks up dep changes.
        args.extend(["-v", f"{tools_pkg}:/opt/llmflows/tools/package.json:ro"])
    for subdir in ("scripts",):
        src = project_root / subdir
        if src.is_dir():
            args.extend(["-v", f"{src}:/opt/llmflows/{subdir}"])
    logger.info("Dev mode: mounting source from %s", project_root)
    return args


def _build_volume_args(
    space_path: str,
    host_home: str,
    google_connectors: Optional[set[str]] = None,
) -> list[str]:
    """Standard volume mounts shared by runner and chat containers."""
    return [
        "-v", f"{space_path}:/workspace",
        "-v", f"{host_home}:/root/.llmflows",
        *google_oauth_volume_args(google_connectors or set()),
        *dev_volume_args(),
    ]


def launch_run_container(
    run_id: str,
    space_path: str,
    flow_snapshot: Optional[str] = None,
    space_id: Optional[str] = None,
    host_home: Optional[str] = None,
) -> Optional[str]:
    """Launch a runner container for a flow run.

    Returns the container ID on success, None on failure.
    """
    if not ensure_image():
        logger.error(
            "Cannot launch run %s — Docker image %s is not available",
            run_id, image_name(),
        )
        return None

    needs_browser_host = _needs_host_browser(flow_snapshot)
    google_connectors = flow_google_connectors(flow_snapshot)
    if needs_browser_host:
        session = get_session()
        try:
            prepare_host_browser_for_run(flow_snapshot, session)
        except Exception as exc:
            logger.error("Failed to prepare host Chrome for run %s: %s", run_id, exc)
            return None
        finally:
            session.close()

    network_args = get_network_args(needs_browser_host=needs_browser_host)
    env_args = _build_env_args(space_id)
    env_args.extend(["-e", "LLMFLOWS_RUNNER=1"])
    env_args.extend(["-e", f"LLMFLOWS_SPACE_HOST_PATH={space_path}"])
    llmflows_host = host_home or os.environ.get("LLMFLOWS_HOST_HOME", str(SYSTEM_DIR))

    cmd = [
        "docker", "run", "-d",
        "--name", f"llmflows-run-{run_id[:8]}",
        "-w", "/workspace",
        *_build_volume_args(space_path, llmflows_host, google_connectors),
        *youtube_port_args(google_connectors),
        *network_args,
        *env_args,
        "--label", f"llmflows.run_id={run_id}",
        "--label", f"llmflows.version={__version__}",
        image_name(),
        "run-daemon", "--run-id", run_id,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(
                "Failed to launch container for run %s: %s",
                run_id, result.stderr.strip(),
            )
            return None
        container_id = result.stdout.strip()
        logger.info("Launched runner container %s for run %s", container_id[:12], run_id)
        return container_id
    except subprocess.TimeoutExpired:
        logger.error("Timeout launching container for run %s", run_id)
        return None
    except FileNotFoundError:
        logger.error("Docker CLI not found — cannot launch containers")
        return None


def is_container_alive(container_id: str) -> bool:
    """Check if a runner container is still running."""
    if not container_id:
        return False
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_container_exit_code(container_id: str) -> Optional[int]:
    """Get the exit code of a stopped container."""
    if not container_id:
        return None
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.ExitCode}}", container_id],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass
    return None


def stop_container(container_id: str, timeout: int = 10) -> bool:
    """Stop a runner container gracefully."""
    if not container_id:
        return False
    try:
        result = subprocess.run(
            ["docker", "stop", "-t", str(timeout), container_id],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def remove_container(container_id: str) -> bool:
    """Remove a stopped runner container."""
    if not container_id:
        return False
    try:
        result = subprocess.run(
            ["docker", "rm", "-f", container_id],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_container_logs(container_id: str, tail: int = 100) -> str:
    """Get recent logs from a runner container."""
    if not container_id:
        return ""
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(tail), container_id],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout + result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def launch_chat_container(
    space_path: str,
    pi_command: list[str],
    env_vars: dict[str, str],
    session_id: str = "",
) -> Optional[subprocess.Popen]:
    """Launch a short-lived container for a chat session.

    Returns a Popen handle for streaming stdout, or None on failure.
    The container is auto-removed on exit.
    """
    network_args = get_network_args(needs_browser_host=False)
    name = f"llmflows-chat-{session_id[:8]}" if session_id else "llmflows-chat"

    cmd = [
        "docker", "run", "-i", "--rm",
        "--name", name,
        *_build_volume_args(space_path, str(SYSTEM_DIR)),
        *network_args,
    ]
    for k, v in env_vars.items():
        cmd.extend(["-e", f"{k}={v}"])

    cmd.append(image_name())
    cmd.extend(pi_command)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        return proc
    except FileNotFoundError:
        logger.error("Docker CLI not found — cannot launch chat container")
        return None


def cleanup_orphan_containers() -> int:
    """Remove any stopped llmflows runner containers. Returns count removed."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "label=llmflows.run_id",
             "--filter", "status=exited", "-q"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return 0

        container_ids = result.stdout.strip().split("\n")
        removed = 0
        for cid in container_ids:
            if remove_container(cid.strip()):
                removed += 1
        if removed:
            logger.info("Cleaned up %d orphan runner containers", removed)
        return removed
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def _needs_host_browser(flow_snapshot: Optional[str]) -> bool:
    """Check if a flow run needs host Chrome (headed browser in Docker)."""
    session = get_session()
    try:
        return flow_needs_host_browser(flow_snapshot, session)
    finally:
        session.close()


def _build_env_args(space_id: Optional[str] = None) -> list[str]:
    """Build --env arguments for API keys, provider credentials, and DATABASE_URL."""
    args = []
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        args.extend(["-e", f"DATABASE_URL={db_url}"])
    dev_home = os.environ.get("LLMFLOWS_DEV_HOME")
    if dev_home:
        args.extend(["-e", f"LLMFLOWS_DEV_HOME={dev_home}"])
    session = get_session()
    try:
        for cfg in session.query(AgentConfig).all():
            args.extend(["-e", f"{cfg.key}={cfg.value}"])
    finally:
        session.close()
    return args
