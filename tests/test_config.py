"""Tests for configuration."""

from llmflows.config import (
    DEFAULT_CONFIG,
    load_system_config,
    find_project_dir,
)


def test_default_config():
    assert "daemon" in DEFAULT_CONFIG
    assert "ui" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["daemon"]["poll_interval_seconds"] == 30
    assert DEFAULT_CONFIG["ui"]["port"] == 4201


def test_load_system_config_defaults():
    config = load_system_config()
    assert config["daemon"]["poll_interval_seconds"] == 30
    assert config["ui"]["port"] == 4201
    assert config["ui"]["host"] == "localhost"


def test_find_project_dir_none(temp_dir):
    result = find_project_dir(temp_dir)
    assert result is None


def test_find_project_dir(temp_dir):
    project_dir = temp_dir / ".llmflows"
    project_dir.mkdir()
    result = find_project_dir(temp_dir)
    assert result.resolve() == project_dir.resolve()


def test_find_project_dir_nested(temp_dir):
    project_dir = temp_dir / ".llmflows"
    project_dir.mkdir()
    nested = temp_dir / "src" / "deep"
    nested.mkdir(parents=True)
    result = find_project_dir(nested)
    assert result.resolve() == project_dir.resolve()
