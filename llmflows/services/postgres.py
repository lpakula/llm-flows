"""Bundled PostgreSQL container for concurrent runner access."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("llmflows.postgres")

PG_CONTAINER = "llmflows-db"
DEFAULT_PG_PORT = 5433
DEFAULT_PG_USER = "llmflows"
DEFAULT_PG_PASSWORD = "llmflows"
DEFAULT_PG_DB = "llmflows"


def compose_file() -> Path:
    return Path(__file__).resolve().parent.parent / "defaults" / "docker-compose.db.yml"


def default_host_database_url(port: int = DEFAULT_PG_PORT) -> str:
    return f"postgresql://{DEFAULT_PG_USER}:{DEFAULT_PG_PASSWORD}@localhost:{port}/{DEFAULT_PG_DB}"


def is_managed_postgres() -> bool:
    return bool(os.environ.get("LLMFLOWS_PG_CONTAINER"))


def runner_database_url(host_url: str) -> str:
    """Return a DATABASE_URL reachable from inside runner/chat containers."""
    if not host_url:
        return host_url

    container = os.environ.get("LLMFLOWS_PG_CONTAINER")
    if container:
        parsed = urlparse(host_url)
        host_port = parsed.hostname or "localhost"
        if host_port in ("localhost", "127.0.0.1", container):
            netloc = parsed.netloc
            if parsed.username:
                auth = f"{parsed.username}"
                if parsed.password:
                    auth += f":{parsed.password}"
                netloc = f"{auth}@{container}:5432"
            else:
                netloc = f"{container}:5432"
            return urlunparse(parsed._replace(netloc=netloc))

    parsed = urlparse(host_url)
    if parsed.hostname in ("localhost", "127.0.0.1"):
        netloc = parsed.netloc.replace(parsed.hostname, "host.docker.internal", 1)
        return urlunparse(parsed._replace(netloc=netloc))
    return host_url


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _compose_cmd() -> list[str]:
    for base in (["docker", "compose"], ["docker-compose"]):
        if shutil.which(base[0]):
            return base
    return ["docker", "compose"]


def _container_healthy() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", PG_CONTAINER],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "healthy"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _container_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", PG_CONTAINER],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def ensure_postgres(*, port: int = DEFAULT_PG_PORT) -> str:
    """Start the bundled Postgres container and configure DATABASE_URL.

    No-op when DATABASE_URL is already set (external database). Returns the
    host-facing database URL.
    """
    existing = os.environ.get("DATABASE_URL")
    if existing:
        return existing

    if not _docker_available():
        raise RuntimeError(
            "Docker is required to run the bundled PostgreSQL database. "
            "Install Docker or set DATABASE_URL to an external PostgreSQL instance."
        )

    from .network import ensure_network

    ensure_network()

    compose = compose_file()
    if not compose.is_file():
        raise FileNotFoundError(f"Postgres compose file not found: {compose}")

    port_str = str(port)
    env = {**os.environ, "LLMFLOWS_DB_PORT": port_str}
    cmd = [*_compose_cmd(), "-f", str(compose), "up", "-d", "--wait"]

    logger.info("Starting bundled Postgres (port %s)", port_str)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Failed to start Postgres container: {detail}")

    host_url = default_host_database_url(port)
    os.environ["DATABASE_URL"] = host_url
    os.environ["LLMFLOWS_PG_CONTAINER"] = PG_CONTAINER

    if not _container_healthy() and not _wait_for_healthy(timeout=30):
        raise RuntimeError("Postgres container did not become healthy in time")

    from ..db.database import reset_engine

    reset_engine()
    return host_url


def _wait_for_healthy(*, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _container_healthy():
            return True
        if not _container_running():
            return False
        time.sleep(0.5)
    return _container_healthy()


def stop_postgres() -> None:
    """Stop the bundled Postgres container (no-op if not running)."""
    if not _docker_available() or not compose_file().is_file():
        return
    subprocess.run(
        [*_compose_cmd(), "-f", str(compose_file()), "stop"],
        capture_output=True,
        text=True,
        timeout=30,
    )
