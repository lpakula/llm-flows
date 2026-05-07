"""Tests for the GitHub channel — mention parsing, repo mapping, enqueue, outbound."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from llmflows.db.models import Base, Flow, FlowRun, FlowStep, Space
from llmflows.services.gateway.github import (
    GitHubChannel,
    MENTION_RE,
    parse_mention,
    _parse_github_remote,
)


# ── Mention parsing ──────────────────────────────────────────────────────────


class TestParseMention:
    def test_basic_mention(self):
        flow, text = parse_mention("@llmflows:feature-develop Add timeout handling")
        assert flow == "feature-develop"
        assert text == "Add timeout handling"

    def test_mention_at_end(self):
        flow, text = parse_mention("Fix the login page timeout.\n\n@llmflows:bugfix")
        assert flow == "bugfix"
        assert text == "Fix the login page timeout."

    def test_mention_inline(self):
        flow, text = parse_mention("Please @llmflows:pr-followup fix the tests")
        assert flow == "pr-followup"
        assert text == "Please fix the tests"

    def test_mention_with_hyphens(self):
        flow, text = parse_mention("@llmflows:feature-from-issue do the thing")
        assert flow == "feature-from-issue"
        assert text == "do the thing"

    def test_no_mention(self):
        flow, text = parse_mention("Just a regular comment")
        assert flow is None
        assert text == ""

    def test_bare_mention_no_flow(self):
        flow, text = parse_mention("@llmflows do something")
        assert flow is None
        assert text == ""

    def test_empty_body(self):
        flow, text = parse_mention("")
        assert flow is None
        assert text == ""

    def test_none_body(self):
        flow, text = parse_mention(None)
        assert flow is None
        assert text == ""

    def test_mention_only(self):
        flow, text = parse_mention("@llmflows:my-flow")
        assert flow == "my-flow"
        assert text == ""

    def test_multiple_mentions_picks_first(self):
        flow, text = parse_mention("@llmflows:first then @llmflows:second")
        assert flow == "first"

    def test_mention_regex_pattern(self):
        assert MENTION_RE.search("@llmflows:test")
        assert MENTION_RE.search("text @llmflows:my-flow more")
        assert not MENTION_RE.search("@llmflows without colon")
        assert not MENTION_RE.search("@llmflows: space-after-colon")


# ── Remote URL parsing ───────────────────────────────────────────────────────


class TestParseGithubRemote:
    def test_ssh_url(self):
        assert _parse_github_remote("git@github.com:owner/repo.git") == "owner/repo"

    def test_https_url(self):
        assert _parse_github_remote("https://github.com/owner/repo.git") == "owner/repo"

    def test_https_no_git_suffix(self):
        assert _parse_github_remote("https://github.com/owner/repo") == "owner/repo"

    def test_ssh_no_git_suffix(self):
        assert _parse_github_remote("git@github.com:owner/repo") == "owner/repo"

    def test_non_github(self):
        assert _parse_github_remote("git@gitlab.com:owner/repo.git") is None

    def test_trailing_whitespace(self):
        assert _parse_github_remote("  https://github.com/org/proj.git  ") == "org/proj"


# ── Channel init and repo map ────────────────────────────────────────────────


@pytest.fixture
def gh_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def gh_channel(gh_db):
    factory = MagicMock(return_value=gh_db)
    return GitHubChannel(
        config={"token": "ghp_test123", "enabled": True},
        session_factory=factory,
    )


class TestGitHubChannel:
    def test_init(self, gh_channel):
        assert gh_channel.name == "github"
        assert gh_channel.token == "ghp_test123"
        assert "run.completed" in gh_channel.subscribed_events

    def test_build_repo_map(self, gh_channel, gh_db):
        space = Space(name="test-space", path="/tmp/test-repo")
        gh_db.add(space)
        gh_db.commit()

        with patch("llmflows.services.gateway.github._git_remote_url",
                    return_value="git@github.com:myorg/myrepo.git"):
            gh_channel._build_repo_map()

        assert "myorg/myrepo" in gh_channel._repo_map
        assert gh_channel._repo_map["myorg/myrepo"]["space_id"] == space.id

    def test_build_repo_map_no_remote(self, gh_channel, gh_db):
        space = Space(name="no-remote", path="/tmp/no-remote")
        gh_db.add(space)
        gh_db.commit()

        with patch("llmflows.services.gateway.github._git_remote_url", return_value=None):
            gh_channel._build_repo_map()

        assert len(gh_channel._repo_map) == 0

    def test_enqueue_flow_found(self, gh_channel, gh_db):
        space = Space(name="test", path="/tmp/test")
        gh_db.add(space)
        gh_db.commit()
        space_id = space.id

        flow = Flow(name="feature-develop", space_id=space_id)
        gh_db.add(flow)
        gh_db.commit()
        flow_id = flow.id

        run_vars = {"TASK_DESCRIPTION": "do stuff", "GITHUB_REF": "issue:1", "GITHUB_EVENT": "issue"}
        gh_channel._enqueue("owner/repo", {"space_id": space_id, "space_name": "test"}, "feature-develop", run_vars)

        gh_db.expire_all()
        runs = gh_db.query(FlowRun).all()
        assert len(runs) == 1
        assert runs[0].flow_id == flow_id
        rv = runs[0].run_variables
        assert rv["TASK_DESCRIPTION"] == "do stuff"
        assert rv["GITHUB_REF"] == "issue:1"

    def test_enqueue_flow_not_found(self, gh_channel, gh_db):
        space = Space(name="test", path="/tmp/test")
        gh_db.add(space)
        gh_db.commit()
        space_id = space.id

        with patch("llmflows.services.gateway.github._gh_api"):
            gh_channel._enqueue(
                "owner/repo",
                {"space_id": space_id, "space_name": "test"},
                "nonexistent-flow",
                {"GITHUB_REF": "issue:1", "GITHUB_EVENT": "issue", "TASK_DESCRIPTION": ""},
            )

        gh_db.expire_all()
        assert gh_db.query(FlowRun).count() == 0

    def test_send_run_completed_no_github_ref(self, gh_channel, gh_db):
        """Runs without GITHUB_REF should be silently skipped."""
        space = Space(name="test", path="/tmp/test")
        gh_db.add(space)
        gh_db.commit()

        run = FlowRun(space_id=space.id, flow_id=None)
        gh_db.add(run)
        gh_db.commit()

        with patch("llmflows.services.gateway.github._gh_api") as mock_api:
            gh_channel.send("run.completed", {"run_id": run.id, "flow_name": "test"})
            mock_api.assert_not_called()


    def test_build_base_vars(self):
        vars = GitHubChannel._build_base_vars("fix the bug", "issue:42", "issue")
        assert vars["TASK_DESCRIPTION"] == "fix the bug"
        assert vars["GITHUB_REF"] == "issue:42"
        assert vars["GITHUB_EVENT"] == "issue"

    def test_is_own_comment(self, gh_channel):
        gh_channel._bot_user = "llmflows-bot"
        assert gh_channel._is_own_comment({"user": {"login": "llmflows-bot"}})
        assert not gh_channel._is_own_comment({"user": {"login": "other-user"}})

    def test_is_own_comment_no_bot_user(self, gh_channel):
        gh_channel._bot_user = None
        assert not gh_channel._is_own_comment({"user": {"login": "anyone"}})

    def test_allowed_users_empty_blocks_all(self, gh_channel):
        gh_channel.allowed_users = set()
        assert not gh_channel._is_allowed_user({"user": {"login": "anyone"}})

    def test_allowed_users_allowlist(self, gh_channel):
        gh_channel.allowed_users = {"alice", "bob"}
        assert gh_channel._is_allowed_user({"user": {"login": "alice"}})
        assert gh_channel._is_allowed_user({"user": {"login": "Bob"}})
        assert not gh_channel._is_allowed_user({"user": {"login": "mallory"}})
