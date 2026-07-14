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
import threading
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .. import __version__
from ..config import SYSTEM_DIR
from ..db.database import get_runner_database_url, get_session
from ..db.models import AgentConfig
from .network import get_network_args
from .browser_host import flow_needs_host_browser, prepare_host_browser_for_run
from .google_host import flow_google_connectors, google_oauth_volume_args, youtube_port_args

logger = logging.getLogger("llmflows.container")

_GITHUB_REPO = "lpakula/llm-flows"
_BUILD_CACHE_DIR = SYSTEM_DIR / "docker-build"

_build_lock = threading.Lock()
_build_state: dict[str, object] = {
    "building": False,
    "error": None,
    "log_lines": [],
    "cancel_requested": False,
    "proc": None,
}
_MAX_BUILD_LOG_LINES = 2000


def _append_build_log(line: str) -> None:
    with _build_lock:
        lines = _build_state.setdefault("log_lines", [])
        if not isinstance(lines, list):
            lines = []
            _build_state["log_lines"] = lines
        lines.append(line)
        if len(lines) > _MAX_BUILD_LOG_LINES:
            del lines[: len(lines) - _MAX_BUILD_LOG_LINES]


def get_runner_build_logs(lines: int = 300) -> list[str]:
    with _build_lock:
        log = _build_state.get("log_lines")
        if not isinstance(log, list):
            return []
        return log[-lines:] if len(log) > lines else list(log)


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
    on_line: Optional[Callable[[str], None]] = None,
    managed: bool = False,
) -> bool:
    """Build the llmflows Docker image. Returns True on success."""
    tag = tag or image_name()
    root = resolve_build_context()
    if not root:
        msg = (
            f"No Docker build context for {tag} — clone "
            f"https://github.com/{_GITHUB_REPO} or set LLMFLOWS_SOURCE"
        )
        logger.error(msg)
        if on_line:
            on_line(msg)
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
    if on_line:
        on_line(f"Building Docker image {tag} from {root}")

    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if managed:
            with _build_lock:
                _build_state["proc"] = proc
                _build_state["cancel_requested"] = False

        assert proc.stdout is not None
        for line in proc.stdout:
            with _build_lock:
                if managed and _build_state.get("cancel_requested"):
                    break
            line = line.rstrip("\n")
            if on_line:
                on_line(line)

        with _build_lock:
            cancelled = managed and bool(_build_state.get("cancel_requested"))

        if cancelled:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            if on_line:
                on_line("Build cancelled by user")
            return False

        rc = proc.wait(timeout=1800)
        if rc != 0 and on_line:
            on_line(f"docker build exited with code {rc}")
        return rc == 0
    except subprocess.TimeoutExpired:
        if on_line:
            on_line("docker build timed out after 30 minutes")
        if proc is not None and proc.poll() is None:
            proc.kill()
        return False
    except FileNotFoundError:
        if on_line:
            on_line("docker build failed — Docker CLI not found")
        return False
    finally:
        if managed:
            with _build_lock:
                _build_state["proc"] = None


def ensure_image(
    *,
    build: bool = True,
    on_status: Optional[Callable[[str], None]] = None,
    quiet: bool = False,
) -> bool:
    """Return True when the runner Docker image exists.

  When *build* is False, only checks presence (fast path for chat/UI).
  When *build* is True and the image is missing, builds it.

    Skipped inside runner containers (``LLMFLOWS_RUNNER=1``).
    When ``quiet`` is True, only errors are reported via ``on_status``.
    """
    if os.environ.get("LLMFLOWS_RUNNER"):
        return True

    tag = image_name()
    if image_exists(tag):
        return True

    if not build:
        return False

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


def runner_image_status() -> dict:
    """Runner image presence and background-build state for the UI."""
    tag = image_name()
    with _build_lock:
        building = bool(_build_state["building"])
        error = _build_state.get("error")
    return {
        "tag": tag,
        "exists": image_exists(tag),
        "building": building,
        "error": str(error) if error else None,
        "docker_available": bool(shutil.which("docker")),
    }


def _background_build_worker() -> None:
    try:
        ok = build_image(on_line=_append_build_log, managed=True)
        with _build_lock:
            cancelled = bool(_build_state.get("cancel_requested"))
        if cancelled:
            with _build_lock:
                _build_state["error"] = "Build cancelled"
        elif ok:
            with _build_lock:
                _build_state["error"] = None
            _append_build_log(f"Runner image {image_name()} ready")
        else:
            err = f"failed to build {image_name()}"
            with _build_lock:
                _build_state["error"] = err
            _append_build_log(err)
    except Exception as exc:
        logger.exception("Background runner image build failed")
        with _build_lock:
            _build_state["error"] = str(exc)
        _append_build_log(str(exc))
    finally:
        with _build_lock:
            _build_state["building"] = False
            _build_state["cancel_requested"] = False
            _build_state["proc"] = None


def cancel_runner_image_build() -> tuple[bool, str]:
    """Cancel an in-progress background runner image build."""
    with _build_lock:
        if not _build_state["building"]:
            return False, "No build in progress"
        _build_state["cancel_requested"] = True
        proc = _build_state.get("proc")

    _append_build_log("Cancelling build…")

    if proc is not None and hasattr(proc, "poll") and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    with _build_lock:
        _build_state["error"] = "Build cancelled"

    return True, "Build cancelled"


def start_runner_image_build() -> tuple[bool, str]:
    """Start a background Docker image build. Returns ``(started, message)``."""
    status = runner_image_status()
    if status["exists"]:
        return False, "Runner image already exists"
    if status["building"]:
        return False, "Build already in progress"
    if not status["docker_available"]:
        return False, "Docker is not available"

    with _build_lock:
        if _build_state["building"]:
            return False, "Build already in progress"
        _build_state["building"] = True
        _build_state["error"] = None
        _build_state["log_lines"] = []
        _build_state["cancel_requested"] = False
        _build_state["proc"] = None

    _append_build_log(f"Starting build for {image_name()}…")

    threading.Thread(target=_background_build_worker, daemon=True).start()
    return True, "Build started"


def per_flow_image_tag(flow_id: str, flow_version: int, llmflows_version: str | None = None) -> str:
    """Tag for a flow's committed runner image at a given flow + llmflows version."""
    return f"{llmflows_version or __version__}-{flow_id}-fv{flow_version}"


def per_flow_image_name(flow_id: str, flow_version: int, llmflows_version: str | None = None) -> str:
    """Docker reference for a flow's committed runner image."""
    return f"llmflows-flow:{per_flow_image_tag(flow_id, flow_version, llmflows_version)}"


def flow_version_from_snapshot(flow_snapshot: Optional[str]) -> int:
    """Read the flow definition version baked into a run snapshot."""
    if not flow_snapshot:
        return 1
    try:
        snap = json.loads(flow_snapshot)
        return int(snap.get("version") or 1)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 1


def resolve_run_image(
    flow_id: Optional[str] = None,
    flow_version: int = 1,
) -> tuple[Optional[str], str]:
    """Pick the Docker image for a flow run.

    Uses the flow-version snapshot when present; otherwise the base llmflows
    runner image. Builds the base image on demand when it is missing.
    """
    if not ensure_image(build=False):
        return None, (
            f"Docker image {image_name()} is not available — "
            "build it from the UI status panel or run: llmflows runner build"
        )

    if flow_id:
        tag = per_flow_image_name(flow_id, flow_version)
        if image_exists(tag):
            logger.info("Using committed flow runner image %s", tag)
            return tag, ""

    return image_name(), ""


def commit_container_to_flow_image(
    container_id: str, flow_id: str, flow_version: int,
) -> tuple[bool, str]:
    """Save a stopped run container as the flow's runner image for this version.

    Only the first successful run at a given flow version creates the image;
    later runs at the same version reuse it.
    """
    if not container_id:
        return False, "No container ID"
    if not flow_id:
        return False, "No flow ID"

    tag = per_flow_image_name(flow_id, flow_version)
    if image_exists(tag):
        logger.info(
            "Runner image %s already exists for flow %s v%s — skipping commit",
            tag, flow_id, flow_version,
        )
        return True, ""

    try:
        result = subprocess.run(
            [
                "docker", "commit",
                "--change", f"LABEL llmflows.flow_id={flow_id}",
                "--change", f"LABEL llmflows.flow_version={flow_version}",
                "--change", f"LABEL llmflows.version={__version__}",
                container_id, tag,
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or "docker commit failed").strip()
            return False, msg
        logger.info(
            "Committed runner container %s to flow image %s (flow v%s)",
            container_id[:12], tag, flow_version,
        )
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Timeout committing flow runner image (>120s)"
    except FileNotFoundError:
        return False, "Docker CLI not found — cannot commit flow runner image"


def invalidate_flow_runner_images(flow_id: str) -> int:
    """Remove all committed runner images for a flow (e.g. after a definition change)."""
    if not flow_id:
        return 0
    refs: list[str] = []
    try:
        result = subprocess.run(
            [
                "docker", "images",
                "--filter", f"label=llmflows.flow_id={flow_id}",
                "-q",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            refs.extend(line.strip() for line in result.stdout.strip().splitlines() if line.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    removed = 0
    for ref in dict.fromkeys(refs):
        if _remove_image(ref):
            removed += 1
            logger.info("Invalidated flow runner image %s for flow %s", ref[:12], flow_id)
    return removed


def _remove_image(image_ref: str) -> bool:
    """Force-remove a Docker image. Returns True when the image is gone."""
    if not image_ref:
        return False
    try:
        result = subprocess.run(
            ["docker", "rmi", "-f", image_ref],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def cleanup_stale_runner_images() -> int:
    """Remove flow runner and base images from other llmflows versions.

    After an upgrade, committed flow images (``llmflows-flow:<version>-<flow>``)
    from the previous version are unused. Legacy formats (``llmflows-flow:<flow>``,
    ``llmflows-apt:*``) and old ``llmflows:<version>`` base images are removed too.
    """
    removed = 0
    current = __version__
    current_prefix = f"{current}-"

    try:
        result = subprocess.run(
            ["docker", "images", "llmflows-flow", "--format", "{{.Tag}}\t{{.ID}}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t", 1)
                if len(parts) != 2:
                    continue
                tag, img_id = parts[0].strip(), parts[1].strip()
                if not tag or tag == "<none>" or not img_id:
                    continue
                if not tag.startswith(current_prefix):
                    if _remove_image(img_id):
                        removed += 1
                        logger.info("Removed stale flow runner image llmflows-flow:%s", tag)

        apt_result = subprocess.run(
            ["docker", "images", "llmflows-apt", "-q"],
            capture_output=True, text=True, timeout=30,
        )
        if apt_result.returncode == 0 and apt_result.stdout.strip():
            for img_id in apt_result.stdout.strip().splitlines():
                img_id = img_id.strip()
                if img_id and _remove_image(img_id):
                    removed += 1
                    logger.info("Removed legacy apt runner image %s", img_id[:12])

        base_result = subprocess.run(
            ["docker", "images", "llmflows", "--format", "{{.Tag}}\t{{.ID}}"],
            capture_output=True, text=True, timeout=30,
        )
        if base_result.returncode == 0 and base_result.stdout.strip():
            for line in base_result.stdout.strip().splitlines():
                parts = line.split("\t", 1)
                if len(parts) != 2:
                    continue
                tag, img_id = parts[0].strip(), parts[1].strip()
                if not tag or tag == "<none>" or not img_id:
                    continue
                if tag in (current, "latest"):
                    continue
                if _remove_image(img_id):
                    removed += 1
                    logger.info("Removed stale base runner image llmflows:%s", tag)

        if removed:
            logger.info("Cleaned up %d stale runner image(s)", removed)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return removed


def cleanup_runner_artifacts(skip: Optional[set[str]] = None) -> dict[str, int]:
    """Reclaim disk space from orphan containers and stale runner images."""
    containers = cleanup_orphan_containers(skip=skip)
    images = cleanup_stale_runner_images()
    return {"containers": containers, "images": images}


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


def _home_volume_args(host_home: str) -> list[str]:
    """Volume mounts for ~/.llmflows inside a runner/chat container.

    Only run-facing subdirs are mounted so runners cannot touch the
    orchestrator DB, credentials, or other spaces' data.
    """
    home = Path(host_home)
    args: list[str] = []
    for sub in ("attachments", "prompts", "chat-sessions"):
        sub_dir = home / sub
        sub_dir.mkdir(parents=True, exist_ok=True)
        args.extend(["-v", f"{sub_dir}:/root/.llmflows/{sub}"])
    config_file = home / "config.toml"
    if config_file.is_file():
        args.extend(["-v", f"{config_file}:/root/.llmflows/config.toml:ro"])
    return args


def _build_volume_args(
    space_path: str,
    host_home: str,
    google_connectors: Optional[set[str]] = None,
) -> list[str]:
    """Standard volume mounts shared by runner and chat containers."""
    return [
        "-v", f"{space_path}:/workspace",
        *_home_volume_args(host_home),
        *google_oauth_volume_args(google_connectors or set()),
        *dev_volume_args(),
    ]


def _hardening_args() -> list[str]:
    """Docker resource limits and security options for runner containers.

    Configurable via the ``[runner]`` section in config.toml:
    ``memory``, ``cpus``, ``pids_limit``, ``drop_capabilities``.
    """
    from ..config import load_system_config

    cfg = load_system_config().get("runner", {})
    args: list[str] = []

    memory = cfg.get("memory", "4g")
    if memory:
        args.extend(["--memory", str(memory)])
    cpus = cfg.get("cpus", 0)
    if cpus:
        args.extend(["--cpus", str(cpus)])
    pids_limit = cfg.get("pids_limit", 2048)
    if pids_limit:
        args.extend(["--pids-limit", str(pids_limit)])

    # Opt-in: may break steps that rely on apt-get or sandboxed Chromium.
    if cfg.get("drop_capabilities", False):
        args.extend([
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--cap-add", "CHOWN",
            "--cap-add", "SETUID",
            "--cap-add", "SETGID",
            "--cap-add", "DAC_OVERRIDE",
            "--cap-add", "FOWNER",
            "--cap-add", "KILL",
        ])
    return args


def _proxy_env_args() -> list[str]:
    """Inject egress proxy env vars when ``[network] proxy_url`` is configured.

    On macOS Docker Desktop the iptables-based network isolation is a no-op,
    so routing runner traffic through a user-provided filtering proxy is the
    portable way to control egress.
    """
    from ..config import load_system_config

    proxy_url = load_system_config().get("network", {}).get("proxy_url", "")
    if not proxy_url:
        return []
    no_proxy = "localhost,127.0.0.1,host.docker.internal"
    args: list[str] = []
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        args.extend(["-e", f"{key}={proxy_url}"])
    for key in ("NO_PROXY", "no_proxy"):
        args.extend(["-e", f"{key}={no_proxy}"])
    return args


def run_container_name(run_id: str) -> str:
    """Deterministic container name for a flow run."""
    return f"llmflows-run-{run_id[:8]}"


def _remove_named_container(name: str) -> None:
    """Remove any leftover container with this name (stopped or ``Created``).

    ``docker run --name`` fails on a name collision, so a container left
    behind by a previous failed launch would block every retry.
    """
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def launch_run_container(
    run_id: str,
    space_path: str,
    flow_snapshot: Optional[str] = None,
    space_id: Optional[str] = None,
    host_home: Optional[str] = None,
    flow_id: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """Launch a runner container for a flow run.

    Returns ``(container_id, error_message)`` — container ID on success,
    ``(None, <reason>)`` on failure so callers can surface the error.
    """
    if not flow_id and flow_snapshot:
        try:
            snap = json.loads(flow_snapshot)
            flow_id = snap.get("id") or flow_id
        except (json.JSONDecodeError, TypeError):
            pass

    flow_version = flow_version_from_snapshot(flow_snapshot)
    run_image, error = resolve_run_image(flow_id, flow_version)
    if not run_image:
        logger.error("Cannot launch run %s — %s", run_id, error)
        return None, error

    needs_browser_host = _needs_host_browser(flow_snapshot)
    google_connectors = flow_google_connectors(flow_snapshot)
    if needs_browser_host:
        session = get_session()
        try:
            prepare_host_browser_for_run(flow_snapshot, session)
        except Exception as exc:
            error = f"Failed to prepare host Chrome: {exc}"
            logger.error("Failed to prepare host Chrome for run %s: %s", run_id, exc)
            return None, error
        finally:
            session.close()

    network_args = get_network_args(needs_browser_host=needs_browser_host)
    env_args = _build_env_args(flow_snapshot)
    env_args.extend(["-e", "LLMFLOWS_RUNNER=1"])
    env_args.extend(["-e", f"LLMFLOWS_SPACE_HOST_PATH={space_path}"])
    env_args.extend(_proxy_env_args())
    llmflows_host = host_home or os.environ.get("LLMFLOWS_HOST_HOME", str(SYSTEM_DIR))

    name = run_container_name(run_id)
    _remove_named_container(name)

    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "-w", "/workspace",
        *_build_volume_args(space_path, llmflows_host, google_connectors),
        *youtube_port_args(google_connectors),
        *network_args,
        *_hardening_args(),
        *env_args,
        "--label", f"llmflows.run_id={run_id}",
        "--label", f"llmflows.version={__version__}",
        *([ "--label", f"llmflows.flow_id={flow_id}"] if flow_id else []),
        *([ "--label", f"llmflows.flow_version={flow_version}"] if flow_id else []),
        run_image,
        "run-daemon", "--run-id", run_id,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            error = result.stderr.strip()
            logger.error("Failed to launch container for run %s: %s", run_id, error)
            # docker run may leave a Created container behind (e.g. failed
            # port bind) — remove it so it doesn't block the next attempt.
            _remove_named_container(name)
            return None, f"Container launch failed: {error}"
        container_id = result.stdout.strip()
        logger.info("Launched runner container %s for run %s", container_id[:12], run_id)
        return container_id, ""
    except subprocess.TimeoutExpired:
        logger.error("Timeout launching container for run %s", run_id)
        return None, "Timeout launching container (docker run took >30s)"
    except FileNotFoundError:
        logger.error("Docker CLI not found — cannot launch containers")
        return None, "Docker CLI not found — install Docker to run flows"


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


def kill_run_container(container_id: str | None) -> bool:
    """Force-stop and remove a runner container for a cancelled run."""
    if not container_id:
        return False
    return remove_container(container_id)


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
        "--label", "llmflows.chat=1",
        "--label", f"llmflows.version={__version__}",
        "-w", "/workspace",
        "-v", f"{space_path}:/workspace",
        *_home_volume_args(str(SYSTEM_DIR)),
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


def cleanup_orphan_containers(skip: Optional[set[str]] = None) -> int:
    """Remove stopped or never-started llmflows runner containers.

    ``Created`` containers are left behind when ``docker run`` fails after
    creating the container object (e.g. port bind or name conflict) and
    would otherwise accumulate and block future launches with the same name.

    Also removes exited chat containers and any stopped container whose name
    starts with ``llmflows-run-`` or ``llmflows-chat-``.

    ``skip`` holds container IDs still tracked by active runs (any prefix
    length) — those are left for the daemon to inspect and remove itself.
    Returns count removed.
    """
    skip = skip or set()

    def _is_tracked(cid: str) -> bool:
        return any(tracked.startswith(cid) or cid.startswith(tracked) for tracked in skip if tracked)

    container_ids: set[str] = set()
    try:
        queries: list[tuple[list[str], str]] = []
        for status in ("exited", "created"):
            queries.append((["docker", "ps", "-a", "--filter", "label=llmflows.run_id"], status))
        queries.append((["docker", "ps", "-a", "--filter", "label=llmflows.chat=1"], "exited"))
        for status in ("exited", "created"):
            queries.append((["docker", "ps", "-a", "--filter", "name=llmflows-run-"], status))
        queries.append((["docker", "ps", "-a", "--filter", "name=llmflows-chat-"], "exited"))
        for base_cmd, status in queries:
            result = subprocess.run(
                [*base_cmd, "--filter", f"status={status}", "-q"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                container_ids.update(result.stdout.strip().split("\n"))

        removed = 0
        for cid in container_ids:
            cid = cid.strip()
            if not cid or _is_tracked(cid):
                continue
            if remove_container(cid):
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


def _flow_providers(flow_snapshot: Optional[str], session) -> Optional[set[str]]:
    """Provider names a flow's steps can reach through their agent aliases.

    Returns None when the snapshot is missing/unreadable (caller falls back
    to passing all credentials). Always includes the ``mini`` (post-run) and
    ``max`` (gate-retry escalation) aliases since the runner may use them.
    """
    if not flow_snapshot:
        return None
    try:
        snap = json.loads(flow_snapshot)
    except (json.JSONDecodeError, TypeError):
        return None

    alias_names = {
        s.get("agent_alias") or "normal"
        for s in snap.get("steps", [])
    }
    alias_names.update({"normal", "mini", "max"})

    from ..db.models import AgentAlias

    providers = {"pi"}
    aliases = session.query(AgentAlias).filter(AgentAlias.name.in_(alias_names)).all()
    for alias in aliases:
        if alias.agent:
            providers.add(alias.agent)
        if alias.model and "/" in alias.model:
            providers.add(alias.model.split("/", 1)[0])
    return providers


def _build_env_args(flow_snapshot: Optional[str] = None) -> list[str]:
    """Build --env arguments for API keys, provider credentials, and DATABASE_URL.

    Only credentials for providers the flow can actually use are passed in —
    a runner never sees API keys for unrelated providers.
    """
    args = []
    db_url = get_runner_database_url() or os.environ.get("DATABASE_URL")
    if db_url:
        args.extend(["-e", f"DATABASE_URL={db_url}"])
    dev_home = os.environ.get("LLMFLOWS_DEV_HOME")
    if dev_home:
        args.extend(["-e", f"LLMFLOWS_DEV_HOME={dev_home}"])
    session = get_session()
    try:
        providers = _flow_providers(flow_snapshot, session)
        for cfg in session.query(AgentConfig).all():
            if providers is not None and cfg.agent not in providers:
                continue
            args.extend(["-e", f"{cfg.key}={cfg.value}"])
    finally:
        session.close()
    return args
