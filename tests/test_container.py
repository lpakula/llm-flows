"""Tests for Docker container image helpers."""

from pathlib import Path
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


def test_ensure_image_skips_inside_runner():
    with patch.dict("os.environ", {"LLMFLOWS_RUNNER": "1"}):
        assert container_mod.ensure_image() is True


def test_ensure_image_returns_true_when_present():
    with patch.dict("os.environ", {}, clear=True):
        with patch.object(container_mod, "image_name", return_value="llmflows:9.9.9"):
            with patch.object(container_mod, "image_exists", return_value=True):
                assert container_mod.ensure_image() is True


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
    assert messages[0].startswith("Docker image llmflows:9.9.9 not found")
    assert "ready" in messages[-1]
