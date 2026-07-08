"""Tests for container ↔ host path helpers."""

from pathlib import Path

from llmflows.utils.paths import (
    CONTAINER_HOME,
    CONTAINER_PKG,
    coerce_space_path_for_db,
    container_path_to_host,
    host_path_to_container_path,
    normalize_gate_failures_for_display,
    normalize_space_path_for_db,
    space_execution_root,
    space_host_path,
    space_local_path,
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


def test_normalize_space_path_for_db_maps_workspace_to_host(monkeypatch):
    monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
    assert normalize_space_path_for_db("/workspace") == "/Users/me/proj"


def test_normalize_space_path_for_db_passthrough_without_host(monkeypatch):
    monkeypatch.delenv("LLMFLOWS_SPACE_HOST_PATH", raising=False)
    assert normalize_space_path_for_db("/workspace") == "/workspace"


def test_space_host_path_resolves(monkeypatch):
    monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "~/my-space")
    assert space_host_path() == str(Path("~/my-space").expanduser().resolve())


def test_coerce_space_path_for_db_rejects_workspace_without_host(monkeypatch):
    import pytest

    monkeypatch.delenv("LLMFLOWS_SPACE_HOST_PATH", raising=False)
    with pytest.raises(ValueError, match="/workspace"):
        coerce_space_path_for_db("/workspace")


def test_coerce_space_path_for_db_maps_workspace_with_host(monkeypatch):
    monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
    assert coerce_space_path_for_db("/workspace") == "/Users/me/proj"


def test_space_local_path_passthrough_on_host(monkeypatch):
    monkeypatch.delenv("LLMFLOWS_SPACE_HOST_PATH", raising=False)
    assert space_local_path("/Users/me/proj") == "/Users/me/proj"


def test_space_local_path_maps_host_root_to_workspace(monkeypatch):
    monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
    assert space_local_path("/Users/me/proj") == "/workspace"


def test_space_local_path_maps_subpath_to_workspace(monkeypatch):
    monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
    assert (
        space_local_path("/Users/me/proj/.llmflows/my-flow/.audit.json")
        == "/workspace/.llmflows/my-flow/.audit.json"
    )


def test_space_execution_root_on_host(monkeypatch):
    monkeypatch.delenv("LLMFLOWS_SPACE_HOST_PATH", raising=False)
    assert space_execution_root("/Users/me/proj") == Path("/Users/me/proj")


def test_space_execution_root_in_container(monkeypatch):
    monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
    assert space_execution_root("/Users/me/proj") == Path("/workspace")


def test_space_execution_root_idempotent_on_workspace(monkeypatch):
    monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
    assert space_execution_root("/workspace") == Path("/workspace")


class _FakeSpace:
    def __init__(self, path):
        self.path = path


def test_build_step_vars_localizes_paths_in_container(monkeypatch):
    from llmflows.services.gate import build_step_vars

    monkeypatch.setenv("LLMFLOWS_SPACE_HOST_PATH", "/Users/me/proj")
    vars_ = build_step_vars({
        "run.id": "abc123",
        "flow.name": "my-flow",
        "flow.dir": "/Users/me/proj/.llmflows/my-flow",
        "run.dir": "/Users/me/proj/.llmflows/my-flow/runs/abc123/artifacts",
        "step.dir": "/Users/me/proj/.llmflows/my-flow/runs/abc123/artifacts/00-step",
    }, _FakeSpace("/Users/me/proj"))
    assert vars_["flow.dir"] == "/workspace/.llmflows/my-flow"
    assert vars_["run.dir"] == "/workspace/.llmflows/my-flow/runs/abc123/artifacts"
    assert vars_["step.dir"] == "/workspace/.llmflows/my-flow/runs/abc123/artifacts/00-step"
    assert vars_["space.dir"] == "/workspace"
    assert vars_["run.id"] == "abc123"


def test_build_step_vars_passthrough_on_host(monkeypatch):
    from llmflows.services.gate import build_step_vars

    monkeypatch.delenv("LLMFLOWS_SPACE_HOST_PATH", raising=False)
    vars_ = build_step_vars({
        "flow.dir": "/Users/me/proj/.llmflows/my-flow",
    }, _FakeSpace("/Users/me/proj"))
    assert vars_["flow.dir"] == "/Users/me/proj/.llmflows/my-flow"
    assert vars_["space.dir"] == "/Users/me/proj"


def test_build_step_vars_flow_vars_do_not_overwrite_computed(monkeypatch):
    from llmflows.services.gate import build_step_vars

    monkeypatch.delenv("LLMFLOWS_SPACE_HOST_PATH", raising=False)
    snapshot = {"variables": {
        "dir": {"value": "SHOULD-NOT-WIN"},
        "name": {"value": "SHOULD-NOT-WIN"},
        "ISSUE": {"value": "42"},
    }}
    vars_ = build_step_vars({
        "flow.name": "my-flow",
        "flow.dir": "/proj/.llmflows/my-flow",
    }, _FakeSpace("/proj"), flow_snapshot=snapshot)
    assert vars_["flow.dir"] == "/proj/.llmflows/my-flow"
    assert vars_["flow.name"] == "my-flow"
    assert vars_["flow.ISSUE"] == "42"
    assert vars_["space.ISSUE"] == "42"


def test_build_step_vars_handles_none_space(monkeypatch):
    from llmflows.services.gate import build_step_vars

    monkeypatch.delenv("LLMFLOWS_SPACE_HOST_PATH", raising=False)
    vars_ = build_step_vars({"run.id": "x"}, None)
    assert vars_ == {"run.id": "x"}
