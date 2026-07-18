"""Tests for Google OAuth host helpers."""

import json

from llmflows.services import google_host
from llmflows.services.google_host import (
    flow_google_connectors,
    google_oauth_volume_args,
    google_tasks_port_args,
    youtube_port_args,
)


def test_flow_google_connectors_detects_all():
    snap = {
        "steps": [
            {"name": "A", "connectors": ["web_search", "google_workspace"]},
            {"name": "B", "connectors": ["youtube"]},
            {"name": "C", "connectors": ["google_tasks"]},
        ]
    }
    assert flow_google_connectors(json.dumps(snap)) == {
        "google_workspace", "youtube", "google_tasks",
    }


def test_flow_google_connectors_empty_snapshot():
    assert flow_google_connectors(None) == set()
    assert flow_google_connectors("not-json") == set()


def test_google_oauth_volume_args_mounts_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMFLOWS_USER_HOME", str(tmp_path))
    args = google_oauth_volume_args({"google_workspace", "youtube", "google_tasks"})
    joined = " ".join(args)
    assert str(tmp_path / ".google-workspace-mcp") in joined
    assert str(tmp_path / ".ytmcp_tokens.json") in joined
    assert str(tmp_path / ".config/google-tasks-mcp") in joined
    assert (tmp_path / ".google-workspace-mcp").is_dir()
    assert (tmp_path / ".ytmcp_tokens.json").is_file()
    assert (tmp_path / ".config/google-tasks-mcp").is_dir()


def test_google_tasks_volume_mounts_credentials_without_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMFLOWS_USER_HOME", str(tmp_path))
    creds = tmp_path / ".google-workspace-mcp" / "credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text("{}")
    args = google_oauth_volume_args({"google_tasks"})
    joined = " ".join(args)
    assert str(creds) in joined
    assert str(tmp_path / ".config/google-tasks-mcp") in joined


def test_youtube_port_args_only_for_youtube(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMFLOWS_USER_HOME", str(tmp_path))
    monkeypatch.setattr(google_host, "_port_in_use", lambda port: False)
    assert youtube_port_args({"youtube"}) == ["-p", "31415:31415"]
    assert youtube_port_args({"google_workspace"}) == []
    assert youtube_port_args(set()) == []


def test_youtube_port_args_skipped_when_token_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMFLOWS_USER_HOME", str(tmp_path))
    monkeypatch.setattr(google_host, "_port_in_use", lambda port: False)
    token = tmp_path / google_host.YOUTUBE_TOKEN_FILE
    token.write_text(json.dumps({"access_token": "abc"}))
    assert youtube_port_args({"youtube"}) == []


def test_youtube_port_args_published_when_token_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMFLOWS_USER_HOME", str(tmp_path))
    monkeypatch.setattr(google_host, "_port_in_use", lambda port: False)
    # An empty/placeholder token file (as created by the volume mount helper)
    # still requires the OAuth callback port.
    (tmp_path / google_host.YOUTUBE_TOKEN_FILE).touch()
    assert youtube_port_args({"youtube"}) == ["-p", "31415:31415"]


def test_youtube_port_args_skipped_when_port_in_use(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMFLOWS_USER_HOME", str(tmp_path))
    monkeypatch.setattr(google_host, "_port_in_use", lambda port: True)
    assert youtube_port_args({"youtube"}) == []


def test_google_tasks_port_args(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMFLOWS_USER_HOME", str(tmp_path))
    monkeypatch.setattr(google_host, "_port_in_use", lambda port: False)
    assert google_tasks_port_args({"google_tasks"}) == ["-p", "3500-3505:3500-3505"]
    assert google_tasks_port_args({"youtube"}) == []
    token = tmp_path / ".config/google-tasks-mcp" / "tokens.json"
    token.parent.mkdir(parents=True)
    token.write_text(json.dumps({"access_token": "abc"}))
    assert google_tasks_port_args({"google_tasks"}) == []


def test_port_in_use_detects_bound_port():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert google_host._port_in_use(port) is True
    assert google_host._port_in_use(port) is False
