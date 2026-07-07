"""Path helpers for Docker container ↔ host filesystem mapping."""

import os
from pathlib import Path
from typing import Optional

CONTAINER_WORKSPACE = "/workspace"
CONTAINER_HOME = "/root/.llmflows"


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

