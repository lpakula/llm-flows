"""Tests for Google OAuth host helpers."""

import json

from llmflows.services.google_host import (
    flow_google_connectors,
    google_oauth_volume_args,
    youtube_port_args,
)


def test_flow_google_connectors_detects_both():
    snap = {
        "steps": [
            {"name": "A", "connectors": ["web_search", "google_workspace"]},
            {"name": "B", "connectors": ["youtube"]},
        ]
    }
    assert flow_google_connectors(json.dumps(snap)) == {"google_workspace", "youtube"}


def test_flow_google_connectors_empty_snapshot():
    assert flow_google_connectors(None) == set()
    assert flow_google_connectors("not-json") == set()


def test_google_oauth_volume_args_mounts_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMFLOWS_USER_HOME", str(tmp_path))
    args = google_oauth_volume_args({"google_workspace", "youtube"})
    assert str(tmp_path / ".google-workspace-mcp") in args[1]
    assert str(tmp_path / ".ytmcp_tokens.json") in args[3]
    assert (tmp_path / ".google-workspace-mcp").is_dir()
    assert (tmp_path / ".ytmcp_tokens.json").is_file()


def test_youtube_port_args_only_for_youtube():
    assert youtube_port_args({"youtube"}) == ["-p", "31415:31415"]
    assert youtube_port_args({"google_workspace"}) == []
    assert youtube_port_args(set()) == []
