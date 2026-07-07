"""Tests for container ↔ host path helpers."""

from llmflows.utils.paths import (
    container_path_to_host,
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
