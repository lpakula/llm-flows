"""Tests for Docker container image helpers."""

from unittest.mock import patch

from llmflows.services import container as container_mod


def test_image_name_defaults_to_version():
    with patch.dict("os.environ", {}, clear=True):
        with patch.object(container_mod, "__version__", "1.2.3"):
            assert container_mod.image_name() == "llmflows:1.2.3"


def test_image_name_respects_env_override():
    with patch.dict("os.environ", {"LLMFLOWS_IMAGE": "llmflows:custom"}):
        assert container_mod.image_name() == "llmflows:custom"


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
                    with patch.object(container_mod, "build_image", return_value=True) as build:
                        assert container_mod.ensure_image(on_status=on_status) is True
                        build.assert_called_once_with("llmflows:9.9.9")
    assert messages[0].startswith("Docker image llmflows:9.9.9 not found")
    assert "ready" in messages[-1]
