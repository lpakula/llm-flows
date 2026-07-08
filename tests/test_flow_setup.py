"""Tests for per-flow tool installation (setup_script / tools dir)."""

import os

from llmflows.services.flow_setup import (
    SETUP_HASH_FILE,
    SETUP_LOG_FILE,
    apply_flow_tools_env,
    ensure_flow_setup,
    flow_tools_dir,
    flow_tools_env,
)


def test_flow_tools_dir_layout(tmp_path):
    tools = flow_tools_dir(tmp_path, "My Flow")
    assert tools == tmp_path / ".llmflows" / "my-flow" / "tools"


def test_flow_tools_env_targets_tools_dir(tmp_path):
    env = flow_tools_env(tmp_path / "tools", base_env={"PATH": "/usr/bin"})
    assert env["PATH"].startswith(str(tmp_path / "tools" / "bin"))
    assert env["PATH"].endswith("/usr/bin")
    assert env["PYTHONUSERBASE"] == str(tmp_path / "tools")
    assert env["npm_config_prefix"] == str(tmp_path / "tools")
    assert env["LLMFLOWS_FLOW_TOOLS_DIR"] == str(tmp_path / "tools")


def test_apply_flow_tools_env_creates_dirs_and_sets_environ(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    monkeypatch.setenv("PATH", "/usr/bin")
    apply_flow_tools_env(tools)
    assert (tools / "bin").is_dir()
    assert os.environ["PYTHONUSERBASE"] == str(tools)
    assert os.environ["PATH"].startswith(str(tools / "bin"))


def test_ensure_flow_setup_noop_without_script(tmp_path):
    ok, error = ensure_flow_setup("", tmp_path / "tools", tmp_path)
    assert ok is True
    assert error == ""
    assert not (tmp_path / "tools").exists()


def test_ensure_flow_setup_runs_script_and_caches(tmp_path):
    tools = tmp_path / "tools"
    script = f'echo installed > "{tools}/bin/marker"'

    ok, error = ensure_flow_setup(script, tools, tmp_path)
    assert ok is True, error
    assert (tools / "bin" / "marker").is_file()
    assert (tools / SETUP_HASH_FILE).is_file()
    assert (tools / SETUP_LOG_FILE).is_file()

    # Second call with the same script must be skipped (marker not rewritten).
    (tools / "bin" / "marker").unlink()
    ok, error = ensure_flow_setup(script, tools, tmp_path)
    assert ok is True
    assert not (tools / "bin" / "marker").exists()

    # Changed script re-runs.
    ok, error = ensure_flow_setup(script + " # v2", tools, tmp_path)
    assert ok is True
    assert (tools / "bin" / "marker").is_file()


def test_ensure_flow_setup_reports_failure_with_output(tmp_path):
    tools = tmp_path / "tools"
    ok, error = ensure_flow_setup("echo broken-dependency; exit 3", tools, tmp_path)
    assert ok is False
    assert "exited with code 3" in error
    assert "broken-dependency" in error
    # Failed setup must not be cached — next run should retry.
    assert not (tools / SETUP_HASH_FILE).exists()
