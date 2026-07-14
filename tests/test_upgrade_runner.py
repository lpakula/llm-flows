"""Tests for upgrade-time runner image build."""

from unittest.mock import patch

from llmflows.services import upgrade as upgrade_mod


def test_build_runner_image_if_missing_skips_when_present():
    with patch.object(upgrade_mod, "image_exists_for_installed_version", return_value=True):
        messages: list[str] = []
        assert upgrade_mod.build_runner_image_if_missing(on_status=messages.append) is True
        assert any("already present" in m for m in messages)


def test_build_runner_image_if_missing_builds_when_absent():
    with patch.object(upgrade_mod, "image_exists_for_installed_version", return_value=False), \
         patch.object(upgrade_mod, "build_runner_image_via_cli", return_value=True) as build:
        assert upgrade_mod.build_runner_image_if_missing() is True
        build.assert_called_once()
