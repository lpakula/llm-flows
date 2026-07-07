"""Path helpers for Docker container ↔ host filesystem mapping."""

import os
from pathlib import Path
from typing import Optional

CONTAINER_WORKSPACE = "/workspace"
CONTAINER_HOME = "/root/.llmflows"
CONTAINER_PKG = "/opt/llmflows/llmflows"


def space_host_path() -> Optional[str]:
    """Host filesystem path for the mounted space inside a runner/chat container."""
    host = os.environ.get("LLMFLOWS_SPACE_HOST_PATH")
    if not host:
        return None
    return str(Path(host).expanduser().resolve())


def normalize_space_path_for_db(path: str) -> str:
    """Map container ``/workspace`` to the host space path before DB storage.

    Runner containers mount the real space at ``/workspace`` but the central DB
    must always store the host path (e.g. ``/Users/me/proj``), never ``/workspace``.
    """
    host = space_host_path()
    if not host:
        return path
    normalized = Path(path).expanduser()
    if str(normalized) == CONTAINER_WORKSPACE or normalized.resolve() == Path(CONTAINER_WORKSPACE).resolve():
        return host
    return str(normalized.resolve())


def coerce_space_path_for_db(path: str) -> str:
    """Normalize a space path and reject bare container ``/workspace`` paths."""
    normalized = normalize_space_path_for_db(path)
    if normalized == CONTAINER_WORKSPACE:
        raise ValueError(
            "Space path cannot be the container mount /workspace; use the host path"
        )
    return str(Path(normalized).expanduser().resolve())


def space_local_path(path: str) -> str:
    """Map a stored (host) space path to the local filesystem.

    The central DB stores the host path (e.g. ``/Users/me/proj``), but inside a
    runner/chat container the space is mounted at ``/workspace``. When running in
    a container (``LLMFLOWS_SPACE_HOST_PATH`` set), translate the host path — and
    any sub-path under it — to the container mount so file reads/writes resolve.
    On the host this is a no-op.
    """
    host = space_host_path()
    if not host:
        return path
    resolved = Path(path).expanduser().resolve()
    host_root = Path(host)
    if resolved == host_root:
        return CONTAINER_WORKSPACE
    try:
        rel = resolved.relative_to(host_root)
        return str(Path(CONTAINER_WORKSPACE) / rel)
    except ValueError:
        return str(resolved)


def resolve_existing_path(
    path: str,
    *,
    space_host_path: Optional[str] = None,
) -> Optional[Path]:
    """Return the first filesystem path that exists for a stored log/asset path.

    Runner containers store paths like ``/workspace/.llmflows/...`` while the
    orchestrator/UI reads from the host. This helper tries both forms.
    """
    if not path:
        return None

    for candidate in _path_candidates(path, space_host_path=space_host_path):
        if candidate.exists():
            return candidate
    return None


def _path_candidates(path: str, *, space_host_path: Optional[str] = None) -> list[Path]:
    candidates: list[Path] = [Path(path)]

    if path.startswith(f"{CONTAINER_WORKSPACE}/"):
        rel = path[len(CONTAINER_WORKSPACE) + 1:]
        if space_host_path:
            candidates.append(Path(space_host_path) / rel)
        if Path(CONTAINER_WORKSPACE).is_dir():
            candidates.append(Path(CONTAINER_WORKSPACE) / rel)

    elif space_host_path:
        try:
            rel = Path(path).resolve().relative_to(Path(space_host_path).resolve())
            candidates.append(Path(CONTAINER_WORKSPACE) / rel)
        except ValueError:
            pass

    if path.startswith(f"{CONTAINER_HOME}/") or path == CONTAINER_HOME:
        from ..config import SYSTEM_DIR

        suffix = path[len(CONTAINER_HOME):].lstrip("/")
        host_home = Path(SYSTEM_DIR)
        candidates.append(host_home / suffix if suffix else host_home)
        if Path(CONTAINER_HOME).is_dir():
            candidates.append(Path(CONTAINER_HOME) / suffix if suffix else Path(CONTAINER_HOME))

    # Preserve order but drop duplicates
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def container_path_to_host(text: str, *, space_host_path: Optional[str] = None) -> str:
    """Rewrite container ``/workspace`` paths to host paths for UI display."""
    if not text or CONTAINER_WORKSPACE not in text:
        return text
    host = space_host_path or os.environ.get("LLMFLOWS_SPACE_HOST_PATH")
    if not host:
        return text
    return text.replace(CONTAINER_WORKSPACE, str(Path(host).resolve()))


def host_path_to_container_path(
    path: str,
    *,
    host_home: Optional[str] = None,
    space_host_path: Optional[str] = None,
) -> str:
    """Map a host filesystem path to its equivalent inside a runner/chat container."""
    if not path:
        return path

    resolved = Path(path).expanduser().resolve()

    home = Path(host_home or os.environ.get("LLMFLOWS_HOME", Path.home() / ".llmflows")).expanduser().resolve()
    try:
        rel = resolved.relative_to(home)
        return f"{CONTAINER_HOME}/{rel}" if rel.parts else CONTAINER_HOME
    except ValueError:
        pass

    if space_host_path:
        space = Path(space_host_path).expanduser().resolve()
        try:
            rel = resolved.relative_to(space)
            return f"{CONTAINER_WORKSPACE}/{rel}"
        except ValueError:
            pass

    try:
        import llmflows

        pkg_root = Path(llmflows.__file__).resolve().parent
        rel = resolved.relative_to(pkg_root)
        return f"{CONTAINER_PKG}/{rel}"
    except ValueError:
        pass

    return path


def normalize_gate_failures_for_display(
    failures: list[dict],
    *,
    space_host_path: Optional[str] = None,
) -> list[dict]:
    """Return gate failure dicts with container paths rewritten for the host UI."""
    if not failures:
        return failures
    normalized: list[dict] = []
    for failure in failures:
        entry = dict(failure)
        for key in ("command", "message", "output"):
            value = entry.get(key)
            if isinstance(value, str):
                entry[key] = container_path_to_host(value, space_host_path=space_host_path)
        normalized.append(entry)
    return normalized

