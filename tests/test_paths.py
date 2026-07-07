"""Tests for container ↔ host path helpers."""

from pathlib import Path

from llmflows.utils.paths import (
    CONTAINER_HOME,
    CONTAINER_PKG,
    container_path_to_host,
    host_path_to_container_path,
    normalize_gate_failures_for_display,
)


def test_container_path_to_host_rewrites_workspace():
    text = "test -f '/workspace/.llmflows/flow/runs/abc/artifacts/_result.md'"
    out = container_path_to_host(text, space_host_path="/Users/me/proj")
    assert out == "test -f '/Users/me/proj/.llmflows/flow/runs/abc/artifacts/_result.md'"


def test_container_path_to_host_unchanged_without_host():
    text = "/workspace/foo"
    assert container_path_to_host(text) == text


def test_normalize_gate_failures_for_display():
    failures = [{
        "command": "test -f '/workspace/.llmflows/x/artifacts/_result.md'",
        "message": "Create /workspace/.llmflows/x/artifacts/_result.md",
        "output": "",
    }]
    out = normalize_gate_failures_for_display(failures, space_host_path="/host/repo")
    assert "/host/repo" in out[0]["command"]
    assert "/workspace" not in out[0]["command"]
    assert "/host/repo" in out[0]["message"]


def test_host_path_to_container_home():
    host_home = "/Users/me/.llmflows"
    path = f"{host_home}/chat-sessions/abc/session"
    out = host_path_to_container_path(path, host_home=host_home)
    assert out == f"{CONTAINER_HOME}/chat-sessions/abc/session"


def test_host_path_to_container_pkg():
    import llmflows

    pkg_root = Path(llmflows.__file__).resolve().parent
    skill = pkg_root / "defaults" / "skills" / "flows"
    out = host_path_to_container_path(str(skill))
    assert out == f"{CONTAINER_PKG}/defaults/skills/flows"
