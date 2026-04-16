"""Tests for configuration."""

from llmflows.config import (
    DEFAULT_CONFIG,
    load_system_config,
    find_space_dir,
)


def test_default_config():
    assert "daemon" in DEFAULT_CONFIG
    assert "ui" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["daemon"]["poll_interval_seconds"] == 30
    assert DEFAULT_CONFIG["ui"]["port"] == 4300


def test_load_system_config_defaults():
    config = load_system_config()
    assert config["daemon"]["poll_interval_seconds"] == 30
    assert config["ui"]["port"] == 4300
    assert config["ui"]["host"] == "localhost"


def test_find_space_dir_none(temp_dir):
    result = find_space_dir(temp_dir)
    assert result is None


def test_find_space_dir(temp_dir):
    space_dir = temp_dir / ".llmflows"
    space_dir.mkdir()
    result = find_space_dir(temp_dir)
    assert result.resolve() == space_dir.resolve()


def test_find_space_dir_nested(temp_dir):
    space_dir = temp_dir / ".llmflows"
    space_dir.mkdir()
    nested = temp_dir / "src" / "deep"
    nested.mkdir(parents=True)
    result = find_space_dir(nested)
    assert result.resolve() == space_dir.resolve()
