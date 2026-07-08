"""Tests for Docker container image helpers."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from llmflows.services import container as container_mod


def test_image_name_defaults_to_version():
    with patch.dict("os.environ", {}, clear=True):
        with patch.object(container_mod, "__version__", "1.2.3"):
            assert container_mod.image_name() == "llmflows:1.2.3"


def test_image_name_respects_env_override():
    with patch.dict("os.environ", {"LLMFLOWS_IMAGE": "llmflows:custom"}):
        assert container_mod.image_name() == "llmflows:custom"


def test_find_project_root_returns_none_without_dockerfile(tmp_path, monkeypatch):
    fake_pkg = tmp_path / "pkg" / "llmflows" / "services"
    fake_pkg.mkdir(parents=True)
    fake_file = fake_pkg / "container.py"
    fake_file.write_text("")
    monkeypatch.setattr(container_mod, "__file__", str(fake_file))
    assert container_mod.find_project_root() is None


def test_resolve_build_context_uses_llmflows_source(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "Dockerfile").write_text("FROM scratch\n")
    with patch.dict("os.environ", {"LLMFLOWS_SOURCE": str(root)}):
        assert container_mod.resolve_build_context() == root.resolve()


def test_release_tag():
    assert container_mod._release_tag("0.51.0") == "v0.51.0"
    assert container_mod._release_tag("v0.51.0") == "v0.51.0"
    assert container_mod._release_tag("unknown") is None


def test_stage_package_build_context(tmp_path, monkeypatch):
    pkg = tmp_path / "llmflows"
    docker = pkg / "docker"
    (docker / "tools").mkdir(parents=True)
    (docker / "scripts").mkdir(parents=True)
    (docker / "Dockerfile").write_text("FROM scratch\n")
    (docker / "pyproject.toml").write_text("[project]\nname='llmflows'\n")
    (docker / "uv.lock").write_text("version = 1\n")
    (docker / "README.md").write_text("readme\n")
    (docker / "tools" / "package.json").write_text("{}\n")
    (docker / "scripts" / "build.py").write_text("# build\n")
    (pkg / "__init__.py").write_text("")

    cache = tmp_path / "cache"
    monkeypatch.setattr(container_mod, "_BUILD_CACHE_DIR", cache)
    monkeypatch.setattr(container_mod, "__version__", "9.9.9")

    import llmflows
    monkeypatch.setattr(llmflows, "__file__", str(pkg / "__init__.py"))

    staged = container_mod.stage_package_build_context()
    assert staged is not None
    assert (staged / "Dockerfile").is_file()
    assert (staged / "llmflows" / "__init__.py").is_file()
    assert (staged / "tools" / "package.json").is_file()
    assert (staged / "uv.lock").is_file()


def test_frontend_build_arg_skips_when_static_present(tmp_path):
    root = tmp_path / "repo"
    static = root / "llmflows" / "ui" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<html></html>")
    assert container_mod._frontend_build_arg(root) == "0"


def test_frontend_build_arg_builds_when_static_missing(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    assert container_mod._frontend_build_arg(root) == "1"


def test_kill_run_container_delegates_to_remove_container():
    with patch.object(container_mod, "remove_container", return_value=True) as mock_rm:
        assert container_mod.kill_run_container("abc123") is True
        mock_rm.assert_called_once_with("abc123")
    assert container_mod.kill_run_container(None) is False


def test_ensure_image_skips_inside_runner():
    with patch.dict("os.environ", {"LLMFLOWS_RUNNER": "1"}):
        assert container_mod.ensure_image() is True


def test_ensure_image_returns_true_when_present():
    with patch.dict("os.environ", {}, clear=True):
        with patch.object(container_mod, "image_name", return_value="llmflows:9.9.9"):
            with patch.object(container_mod, "image_exists", return_value=True):
                assert container_mod.ensure_image() is True


def _launch_with_mocked_docker(docker_run_result, flow_id=None):
    """Run launch_run_container with docker subprocess calls mocked."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["docker", "rm"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return docker_run_result

    with patch.object(container_mod, "resolve_run_image", return_value=("llmflows:9.9.9", "")), \
         patch.object(container_mod, "_needs_host_browser", return_value=False), \
         patch.object(container_mod, "get_network_args", return_value=[]), \
         patch.object(container_mod, "_build_env_args", return_value=[]), \
         patch.object(container_mod, "dev_volume_args", return_value=[]), \
         patch.object(container_mod.subprocess, "run", side_effect=fake_run):
        result = container_mod.launch_run_container(
            "run12345abc", "/space", flow_id=flow_id,
        )
    return result, calls


def test_launch_run_container_returns_error_when_image_missing():
    with patch.object(container_mod, "resolve_run_image", return_value=(None, "Docker image missing")):
        cid, error = container_mod.launch_run_container("run12345abc", "/space")
    assert cid is None
    assert "missing" in error


def test_launch_run_container_adds_flow_id_label():
    ok = SimpleNamespace(returncode=0, stdout="deadbeef123\n", stderr="")
    (_, _), calls = _launch_with_mocked_docker(ok, flow_id="abc123")
    run_cmd = [c for c in calls if c[:2] == ["docker", "run"]][0]
    assert "llmflows.flow_id=abc123" in run_cmd


def test_per_flow_image_name():
    with patch.object(container_mod, "__version__", "0.52.0"):
        assert container_mod.per_flow_image_name("abc123", 3) == "llmflows-flow:0.52.0-abc123-fv3"


def test_resolve_run_image_uses_committed_flow_image():
    with patch.object(container_mod, "ensure_image", return_value=True), \
         patch.object(container_mod, "__version__", "0.52.0"), \
         patch.object(container_mod, "image_exists", side_effect=lambda tag: tag == "llmflows-flow:0.52.0-abc123-fv2"), \
         patch.object(container_mod, "image_name", return_value="llmflows:0.52.0"):
        tag, error = container_mod.resolve_run_image("abc123", 2)
    assert error == ""
    assert tag == "llmflows-flow:0.52.0-abc123-fv2"


def test_resolve_run_image_falls_back_to_base():
    with patch.object(container_mod, "ensure_image", return_value=True), \
         patch.object(container_mod, "image_exists", return_value=False), \
         patch.object(container_mod, "image_name", return_value="llmflows:1.0.0"):
        tag, error = container_mod.resolve_run_image("abc123", 1)
    assert error == ""
    assert tag == "llmflows:1.0.0"


def test_commit_container_to_flow_image():
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(container_mod, "__version__", "0.52.0"), \
         patch.object(container_mod, "image_exists", return_value=False), \
         patch.object(container_mod.subprocess, "run", side_effect=fake_run):
        ok, error = container_mod.commit_container_to_flow_image("container123", "abc123", 2)
    assert ok is True
    assert error == ""
    assert calls[0][:2] == ["docker", "commit"]
    assert calls[0][-1] == "llmflows-flow:0.52.0-abc123-fv2"


def test_commit_container_skips_when_image_exists():
    with patch.object(container_mod, "__version__", "0.52.0"), \
         patch.object(container_mod, "image_exists", return_value=True), \
         patch.object(container_mod.subprocess, "run") as run:
        ok, error = container_mod.commit_container_to_flow_image("container123", "abc123", 2)
    assert ok is True
    assert error == ""
    run.assert_not_called()


def test_flow_version_from_snapshot():
    snap = json.dumps({"id": "abc", "version": 4, "steps": []})
    assert container_mod.flow_version_from_snapshot(snap) == 4
    assert container_mod.flow_version_from_snapshot(None) == 1


def test_cleanup_stale_runner_images_removes_old_versions():
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["docker", "images", "llmflows-flow"]:
            return SimpleNamespace(
                returncode=0,
                stdout="0.51.0-abc123\timg-old\n0.52.0-def456\timg-current\n",
                stderr="",
            )
        if cmd[:3] == ["docker", "images", "llmflows-apt"]:
            return SimpleNamespace(returncode=0, stdout="apt-img\n", stderr="")
        if cmd[:3] == ["docker", "images", "llmflows"]:
            return SimpleNamespace(returncode=0, stdout="0.51.0\tbase-old\n", stderr="")
        if cmd[:3] == ["docker", "rmi", "-f"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(container_mod, "__version__", "0.52.0"), \
         patch.object(container_mod.subprocess, "run", side_effect=fake_run):
        removed = container_mod.cleanup_stale_runner_images()
    assert removed == 3
    rmi_targets = [c[3] for c in calls if c[:3] == ["docker", "rmi", "-f"]]
    assert "img-old" in rmi_targets
    assert "apt-img" in rmi_targets
    assert "base-old" in rmi_targets
    assert "img-current" not in rmi_targets


def test_cleanup_runner_artifacts_combines_containers_and_images():
    with patch.object(container_mod, "cleanup_orphan_containers", return_value=2) as containers, \
         patch.object(container_mod, "cleanup_stale_runner_images", return_value=4) as images:
        result = container_mod.cleanup_runner_artifacts(skip={"tracked"})
    assert result == {"containers": 2, "images": 4}
    containers.assert_called_once_with(skip={"tracked"})
    images.assert_called_once()


def test_launch_run_container_success_removes_stale_name_first():
    ok = SimpleNamespace(returncode=0, stdout="deadbeef123\n", stderr="")
    (cid, error), calls = _launch_with_mocked_docker(ok)
    assert cid == "deadbeef123"
    assert error == ""
    # A stale container with the same name is removed before docker run.
    assert calls[0][:3] == ["docker", "rm", "-f"]
    assert calls[0][3] == "llmflows-run-run12345"
    assert calls[1][:2] == ["docker", "run"]


def test_launch_run_container_surfaces_docker_stderr():
    failed = SimpleNamespace(
        returncode=125, stdout="",
        stderr="Bind for 0.0.0.0:31415 failed: port is already allocated",
    )
    (cid, error), calls = _launch_with_mocked_docker(failed)
    assert cid is None
    assert "port is already allocated" in error
    # Leftover Created container is removed after the failed launch too.
    rm_calls = [c for c in calls if c[:2] == ["docker", "rm"]]
    assert len(rm_calls) == 2


def test_cleanup_orphan_containers_includes_created_and_skips_tracked():
    removed: list[str] = []

    def fake_run(cmd, **kwargs):
        if "status=exited" in cmd:
            return SimpleNamespace(returncode=0, stdout="aaa111\nbbb222\n", stderr="")
        if "status=created" in cmd:
            return SimpleNamespace(returncode=0, stdout="ccc333\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(container_mod.subprocess, "run", side_effect=fake_run), \
         patch.object(container_mod, "remove_container", side_effect=lambda cid: removed.append(cid) or True):
        # bbb222 is tracked by an active run (full ID in DB) — must be skipped.
        count = container_mod.cleanup_orphan_containers(skip={"bbb222fullcontainerid"})

    assert count == 2
    assert sorted(removed) == ["aaa111", "ccc333"]


def test_home_volume_args_full_mount_with_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    args = container_mod._home_volume_args("/Users/me/.llmflows")
    assert args == ["-v", "/Users/me/.llmflows:/root/.llmflows"]


def test_home_volume_args_scoped_with_external_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/llmflows")
    (tmp_path / "config.toml").write_text("[daemon]\n")
    args = container_mod._home_volume_args(str(tmp_path))
    joined = " ".join(args)
    assert f"{tmp_path}/attachments:/root/.llmflows/attachments" in joined
    assert f"{tmp_path}/prompts:/root/.llmflows/prompts" in joined
    assert f"{tmp_path}/config.toml:/root/.llmflows/config.toml:ro" in joined
    # The full home (and thus the SQLite DB) must NOT be mounted.
    assert f"{tmp_path}:/root/.llmflows " not in joined + " "


def test_proxy_env_args(monkeypatch):
    with patch("llmflows.config.load_system_config", return_value={
        "network": {"proxy_url": "http://host.docker.internal:3128"},
    }):
        args = container_mod._proxy_env_args()
    joined = " ".join(args)
    assert "HTTP_PROXY=http://host.docker.internal:3128" in joined
    assert "HTTPS_PROXY=http://host.docker.internal:3128" in joined
    assert "NO_PROXY=localhost,127.0.0.1,host.docker.internal" in joined


def test_proxy_env_args_empty_without_config():
    with patch("llmflows.config.load_system_config", return_value={}):
        assert container_mod._proxy_env_args() == []


def test_hardening_args_defaults():
    with patch("llmflows.config.load_system_config", return_value={}):
        args = container_mod._hardening_args()
    joined = " ".join(args)
    assert "--memory 4g" in joined
    assert "--pids-limit 2048" in joined
    assert "--cap-drop" not in joined


def test_flow_providers_filters_by_step_aliases(test_db):
    from llmflows.db.models import AgentAlias

    test_db.add(AgentAlias(name="normal", type="pi", agent="anthropic", model="claude-x"))
    test_db.add(AgentAlias(name="mini", type="pi", agent="openai", model="gpt-mini"))
    test_db.add(AgentAlias(name="research", type="pi", agent="google", model="gemini-pro"))
    test_db.commit()

    snap = json.dumps({"steps": [{"name": "a", "agent_alias": "normal"}]})
    providers = container_mod._flow_providers(snap, test_db)
    assert "pi" in providers
    assert "anthropic" in providers
    # mini (post-run) and max (gate escalation) are always considered.
    assert "openai" in providers
    # Unused aliases' providers are excluded — their keys never enter the container.
    assert "google" not in providers


def test_flow_providers_none_without_snapshot(test_db):
    assert container_mod._flow_providers(None, test_db) is None
    assert container_mod._flow_providers("not-json", test_db) is None


def test_hardening_args_drop_capabilities_opt_in():
    with patch("llmflows.config.load_system_config", return_value={
        "runner": {"drop_capabilities": True, "memory": "", "pids_limit": 0},
    }):
        args = container_mod._hardening_args()
    joined = " ".join(args)
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in joined
    assert "--memory" not in joined


def test_ensure_image_builds_when_missing():
    messages: list[str] = []

    def on_status(msg: str) -> None:
        messages.append(msg)

    with patch.dict("os.environ", {}, clear=True):
        with patch.object(container_mod, "image_name", return_value="llmflows:9.9.9"):
            with patch.object(container_mod, "image_exists", return_value=False):
                with patch.object(container_mod.shutil, "which", return_value="/usr/bin/docker"):
                    with patch.object(container_mod, "find_project_root", return_value=Path("/repo")):
                        with patch.object(container_mod, "build_image", return_value=True) as build:
                            assert container_mod.ensure_image(on_status=on_status) is True
                            build.assert_called_once_with("llmflows:9.9.9")
    assert "building llmflows:9.9.9" in messages[0]
