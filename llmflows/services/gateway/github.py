"""GitHub channel for llm-flows — polls for @llmflows:flow-name mentions.

Scans issue bodies, issue comments, PR comments, and PR review comments
for ``@llmflows:flow-name`` mentions.  The surrounding text becomes
``TASK_DESCRIPTION``; additional GitHub context (issue body, PR branch,
review comments, etc.) is passed as run variables.

On ``run.completed``, posts a summary comment back to the linked issue or PR.
"""

import json
import logging
import re
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from ...db.models import FlowRun
from ..flow import FlowService
from ..run import RunService
from ..space import SpaceService

logger = logging.getLogger("llmflows.github")

MENTION_RE = re.compile(r"@llmflows:([\w][\w-]*)")

_MAX_COMMENT_BODY = 60_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gh_api(endpoint: str, token: str, method: str = "GET", body: dict | None = None) -> Any:
    """Call the GitHub REST API via curl (no extra Python deps)."""
    url = f"https://api.github.com{endpoint}"
    cmd = ["curl", "-sf", "-H", f"Authorization: token {token}",
           "-H", "Accept: application/vnd.github+json", url]
    if method == "POST":
        cmd[1:1] = ["-X", "POST"]
        if body:
            cmd += ["-d", json.dumps(body)]
    elif method == "PATCH":
        cmd[1:1] = ["-X", "PATCH"]
        if body:
            cmd += ["-d", json.dumps(body)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.debug("GitHub API error %s: %s", endpoint, result.stderr[:200])
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except Exception:
        logger.debug("GitHub API call failed: %s", endpoint, exc_info=True)
        return None


def _parse_github_remote(url: str) -> Optional[str]:
    """Extract ``owner/repo`` from a git remote URL."""
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # SSH: git@github.com:owner/repo
    m = re.search(r"github\.com[:/](.+/.+)$", url)
    if m:
        return m.group(1)
    return None


def _git_remote_url(path: str) -> Optional[str]:
    """Read origin remote URL from a git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def parse_mention(body: str) -> tuple[Optional[str], str]:
    """Extract ``(flow_name, task_description)`` from a comment body."""
    if not body:
        return None, ""
    match = MENTION_RE.search(body)
    if not match:
        return None, ""
    flow_name = match.group(1)
    text = body[:match.start()] + body[match.end():]
    text = re.sub(r"  +", " ", text).strip()
    return flow_name, text


def _truncate(text: str, limit: int = _MAX_COMMENT_BODY) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n…(truncated)"


# ---------------------------------------------------------------------------
# GitHub Channel
# ---------------------------------------------------------------------------

class GitHubChannel:
    """GitHub polling channel — triggers flows from ``@llmflows:flow-name`` mentions."""

    name = "github"
    subscribed_events = ["run.completed"]

    def __init__(self, config: dict[str, Any], session_factory):
        self.config = config
        self.session_factory = session_factory
        self.token: str = config.get("token", "")
        self.allowed_users: set[str] = {u.lower() for u in config.get("allowed_users", [])}
        self._poll_interval = config.get("poll_interval_seconds", 60)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._repo_map: dict[str, dict] = {}  # "owner/repo" -> {"space_id": ..., "space_path": ...}
        self._last_checked: dict[str, str] = {}  # "owner/repo" -> ISO timestamp
        self._active_refs: set[tuple[str, str]] = set()  # (GITHUB_REF, flow_name) pairs with recent runs
        self._bot_user: Optional[str] = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.token:
            logger.warning("GitHub channel: no token configured, skipping")
            return
        self._resolve_bot_user()
        self._build_repo_map()
        if not self._repo_map:
            logger.info("GitHub channel: no spaces with GitHub remotes found")
            return
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="github-poll")
        self._thread.start()
        logger.info("GitHub channel started (polling %d repos every %ds)",
                     len(self._repo_map), self._poll_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self._thread = None
        logger.info("GitHub channel stopped")

    # ── repo-to-space mapping ─────────────────────────────────────────────

    def _build_repo_map(self) -> None:
        """Auto-detect GitHub repos from registered spaces' git remotes."""
        session = self.session_factory()
        try:
            spaces = SpaceService(session).list_all()
            for space in spaces:
                remote = _git_remote_url(space.path)
                if not remote:
                    continue
                owner_repo = _parse_github_remote(remote)
                if owner_repo:
                    self._repo_map[owner_repo] = {
                        "space_id": space.id,
                        "space_path": space.path,
                        "space_name": space.name,
                    }
                    logger.debug("Mapped repo %s -> space %s", owner_repo, space.name)
        finally:
            session.close()

    def _resolve_bot_user(self) -> None:
        """Fetch the authenticated user's login to skip self-authored comments."""
        data = _gh_api("/user", self.token)
        if data and "login" in data:
            self._bot_user = data["login"]
            logger.debug("GitHub bot user: %s", self._bot_user)

    # ── polling loop ──────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_all_repos()
            except Exception:
                logger.exception("Error in GitHub polling loop")
            self._stop_event.wait(self._poll_interval)

    def _poll_all_repos(self) -> None:
        self._refresh_active_refs()
        for repo, space_info in list(self._repo_map.items()):
            try:
                self._poll_repo(repo, space_info)
            except Exception:
                logger.exception("Error polling repo %s", repo)

    def _refresh_active_refs(self) -> None:
        """Update the set of GITHUB_REF values that have recent or in-progress runs.

        Includes both incomplete runs and runs created in the last 24 hours,
        so a daemon restart doesn't re-trigger recently processed mentions.
        """
        from datetime import timedelta
        session = self.session_factory()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            recent_runs = (
                session.query(FlowRun)
                .filter(
                    (FlowRun.completed_at.is_(None)) |
                    (FlowRun.created_at >= cutoff)
                )
                .all()
            )
            refs = set()
            for run in recent_runs:
                rv = run.run_variables
                if rv and rv.get("GITHUB_REF"):
                    refs.add((rv["GITHUB_REF"], run.flow_name or ""))
            self._active_refs = refs
        finally:
            session.close()

    def _poll_repo(self, repo: str, space_info: dict) -> None:
        since = self._last_checked.get(repo)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # On first poll, only look at comments from the last 5 minutes to avoid
        # replaying the entire comment history.
        if not since:
            from datetime import timedelta
            since = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Poll issue/PR conversation comments (newest first — only latest per issue+flow triggers)
        comments = _gh_api(
            f"/repos/{repo}/issues/comments?since={since}&sort=created&direction=desc&per_page=100",
            self.token,
        )
        if comments and isinstance(comments, list):
            triggered: set[tuple[str, str]] = set()  # (issue_url, flow_name)
            for comment in comments:
                self._process_issue_comment(repo, space_info, comment, triggered)

        # Poll inline PR review comments (newest first)
        review_comments = _gh_api(
            f"/repos/{repo}/pulls/comments?since={since}&sort=created&direction=desc&per_page=100",
            self.token,
        )
        if review_comments and isinstance(review_comments, list):
            triggered_review: set[tuple[str, str]] = set()
            for comment in review_comments:
                self._process_review_comment(repo, space_info, comment, triggered_review)

        self._last_checked[repo] = now

    # ── event processing ──────────────────────────────────────────────────

    def _is_own_comment(self, comment: dict) -> bool:
        if not self._bot_user:
            return False
        user = comment.get("user", {})
        return user.get("login") == self._bot_user

    def _is_allowed_user(self, comment_or_issue: dict) -> bool:
        """Check if the comment/issue author is in the allowed_users list.

        Empty allowlist means no one can trigger — allowed_users must be configured.
        """
        if not self.allowed_users:
            return False
        login = comment_or_issue.get("user", {}).get("login", "")
        return login.lower() in self.allowed_users

    def _process_issue_comment(self, repo: str, space_info: dict, comment: dict,
                               triggered: set[tuple[str, str]]) -> None:
        """Handle an issue or PR conversation comment.

        Comments are processed newest-first. ``triggered`` tracks which
        (issue_url, flow_name) pairs already have a newer comment being
        processed — older duplicates just get 👀 without enqueuing.
        """
        if self._is_own_comment(comment):
            return
        if not self._is_allowed_user(comment):
            return

        flow_name, task = parse_mention(comment.get("body", ""))
        if not flow_name:
            return

        if self._has_eyes_reaction(repo, "issue_comment", comment["id"]):
            return

        issue_url = comment.get("issue_url", "")
        trigger_key = (issue_url, flow_name)

        if trigger_key in triggered:
            self._react_eyes(repo, "issue_comment", comment["id"])
            logger.info("Marked older comment %s with 👀 (newer comment already triggered %s)", comment["id"], flow_name)
            return

        self._react_eyes(repo, "issue_comment", comment["id"])
        triggered.add(trigger_key)

        issue_data = _gh_api(issue_url.replace("https://api.github.com", ""), self.token) if issue_url else None
        if not issue_data:
            return

        is_pr = "pull_request" in issue_data
        if is_pr:
            event_type = "pr_comment"
            github_ref = f"pr:{issue_data['number']}"
        else:
            event_type = "issue_comment"
            github_ref = f"issue:{issue_data['number']}"

        if (github_ref, flow_name) in self._active_refs:
            logger.info("Skipping comment %s — recent run exists for %s (%s)", comment["id"], github_ref, flow_name)
            return

        run_vars = self._build_base_vars(task, github_ref, event_type)
        self._add_issue_vars(run_vars, issue_data)

        if is_pr:
            self._add_pr_context(run_vars, repo, issue_data["number"])

        self._enqueue(repo, space_info, flow_name, run_vars)

    def _process_review_comment(self, repo: str, space_info: dict, comment: dict,
                                triggered: set[tuple[str, str]]) -> None:
        """Handle an inline PR review comment.

        Same newest-first dedup as ``_process_issue_comment``.
        """
        if self._is_own_comment(comment):
            return
        if not self._is_allowed_user(comment):
            return

        flow_name, task = parse_mention(comment.get("body", ""))
        if not flow_name:
            return

        if self._has_eyes_reaction(repo, "review_comment", comment["id"]):
            return

        pr_url = comment.get("pull_request_url", "")
        trigger_key = (pr_url, flow_name)

        if trigger_key in triggered:
            self._react_eyes(repo, "review_comment", comment["id"])
            logger.info("Marked older review comment %s with 👀 (newer comment already triggered %s)", comment["id"], flow_name)
            return

        self._react_eyes(repo, "review_comment", comment["id"])
        triggered.add(trigger_key)

        pr_data = _gh_api(pr_url.replace("https://api.github.com", ""), self.token) if pr_url else None
        if not pr_data:
            return

        github_ref = f"pr:{pr_data['number']}"
        if (github_ref, flow_name) in self._active_refs:
            logger.info("Skipping review comment — recent run exists for %s (%s)", github_ref, flow_name)
            return

        run_vars = self._build_base_vars(task, github_ref, "pr_review")
        self._add_issue_vars(run_vars, pr_data)
        self._add_pr_context(run_vars, repo, pr_data["number"])
        self._enqueue(repo, space_info, flow_name, run_vars)

    # ── variable builders ─────────────────────────────────────────────────

    @staticmethod
    def _build_base_vars(task: str, github_ref: str, event: str) -> dict[str, str]:
        return {
            "TASK_DESCRIPTION": task,
            "GITHUB_REF": github_ref,
            "GITHUB_EVENT": event,
        }

    @staticmethod
    def _add_issue_vars(run_vars: dict, issue: dict) -> None:
        run_vars["ISSUE_NUMBER"] = str(issue.get("number", ""))
        run_vars["ISSUE_TITLE"] = issue.get("title", "")
        run_vars["ISSUE_BODY"] = _truncate(issue.get("body", "") or "")
        run_vars["ISSUE_URL"] = issue.get("html_url", "")

    def _add_pr_context(self, run_vars: dict, repo: str, pr_number: int) -> None:
        """Fetch full PR metadata, conversation comments, and review comments."""
        pr_data = _gh_api(f"/repos/{repo}/pulls/{pr_number}", self.token)
        if pr_data:
            run_vars["PR_NUMBER"] = str(pr_number)
            run_vars["PR_BRANCH"] = pr_data.get("head", {}).get("ref", "")
            run_vars["PR_TITLE"] = pr_data.get("title", "")
            run_vars["PR_BODY"] = _truncate(pr_data.get("body", "") or "")
            run_vars["PR_URL"] = pr_data.get("html_url", "")

        # Conversation comments
        conv_comments = _gh_api(
            f"/repos/{repo}/issues/{pr_number}/comments?per_page=100", self.token,
        )
        if conv_comments and isinstance(conv_comments, list):
            parts = []
            for c in conv_comments:
                user = c.get("user", {}).get("login", "?")
                body = c.get("body", "")
                parts.append(f"**{user}**: {body}")
            run_vars["PR_COMMENTS"] = _truncate("\n\n---\n\n".join(parts))

        # Inline review comments
        review_comments = _gh_api(
            f"/repos/{repo}/pulls/{pr_number}/comments?per_page=100", self.token,
        )
        if review_comments and isinstance(review_comments, list):
            parts = []
            for c in review_comments:
                user = c.get("user", {}).get("login", "?")
                path = c.get("path", "?")
                line = c.get("original_line") or c.get("line") or "?"
                body = c.get("body", "")
                parts.append(f"**{user}** on `{path}:{line}`: {body}")
            run_vars["PR_REVIEW_COMMENTS"] = _truncate("\n\n---\n\n".join(parts))

    # ── reactions ─────────────────────────────────────────────────────────

    def _has_eyes_reaction(self, repo: str, kind: str, item_id: int) -> bool:
        """Check if the bot already reacted with 👀 (meaning we already processed this)."""
        if not self._bot_user:
            return False
        if kind == "issue":
            endpoint = f"/repos/{repo}/issues/{item_id}/reactions"
        elif kind == "issue_comment":
            endpoint = f"/repos/{repo}/issues/comments/{item_id}/reactions"
        elif kind == "review_comment":
            endpoint = f"/repos/{repo}/pulls/comments/{item_id}/reactions"
        else:
            return False
        reactions = _gh_api(endpoint, self.token)
        if not reactions or not isinstance(reactions, list):
            return False
        return any(
            r.get("content") == "eyes" and r.get("user", {}).get("login") == self._bot_user
            for r in reactions
        )

    def _react_eyes(self, repo: str, kind: str, item_id: int) -> None:
        """Add 👀 reaction so the author knows the mention was picked up."""
        if kind == "issue":
            endpoint = f"/repos/{repo}/issues/{item_id}/reactions"
        elif kind == "issue_comment":
            endpoint = f"/repos/{repo}/issues/comments/{item_id}/reactions"
        elif kind == "review_comment":
            endpoint = f"/repos/{repo}/pulls/comments/{item_id}/reactions"
        else:
            return
        _gh_api(endpoint, self.token, method="POST", body={"content": "eyes"})

    # ── enqueue ───────────────────────────────────────────────────────────

    def _enqueue(self, repo: str, space_info: dict, flow_name: str, run_vars: dict) -> None:
        session = self.session_factory()
        try:
            flow_svc = FlowService(session)
            flow = flow_svc.get_by_name(flow_name, space_id=space_info["space_id"])
            if not flow:
                logger.warning("GitHub: flow '%s' not found in space '%s' (repo %s)",
                               flow_name, space_info["space_name"], repo)
                github_ref = run_vars.get("GITHUB_REF", "")
                self._post_error_comment(repo, github_ref,
                                         f"Flow `{flow_name}` not found in space `{space_info['space_name']}`.")
                return

            run_svc = RunService(session)
            run = run_svc.enqueue(
                space_id=space_info["space_id"],
                flow_id=flow.id,
                run_variables=run_vars,
            )
            logger.info("GitHub: enqueued flow '%s' run %s for %s (repo %s)",
                         flow_name, run.id, run_vars.get("GITHUB_REF", "?"), repo)

            github_ref = run_vars.get("GITHUB_REF", "")
            self._active_refs.add((github_ref, flow_name))
        finally:
            session.close()

    # ── outbound: post results back to GitHub ─────────────────────────────

    def send(self, event: str, payload: dict[str, Any]) -> None:
        if event != "run.completed":
            return

        run_id = payload.get("run_id")
        if not run_id:
            return

        session = self.session_factory()
        try:
            run = session.query(FlowRun).filter_by(id=run_id).first()
            if not run:
                return

            rv = run.run_variables
            if not rv:
                return
            github_ref = rv.get("GITHUB_REF", "")
            if not github_ref:
                return

            self._active_refs.discard((github_ref, run.flow_name or ""))

            space = SpaceService(session).get(run.space_id)
            if not space:
                return
            remote = _git_remote_url(space.path)
            if not remote:
                return
            repo = _parse_github_remote(remote)
            if not repo:
                return

            self._post_run_comment(repo, run, github_ref, space.path, payload)
        finally:
            session.close()

    def _post_run_comment(self, repo: str, run: FlowRun, github_ref: str,
                          space_path: str, payload: dict) -> None:
        """Post a summary comment on the linked issue or PR."""
        ref_type, _, ref_num = github_ref.partition(":")
        if not ref_num:
            return

        flow_name = payload.get("flow_name", "?")
        outcome = payload.get("outcome", "completed")
        inbox_message = payload.get("inbox_message") or payload.get("summary") or ""

        lines = [f"**llm-flows** `{flow_name}` — {outcome}"]

        meta: list[str] = []
        dur = payload.get("duration_seconds")
        if dur is not None:
            secs = int(dur)
            if secs < 60:
                meta.append(f"{secs}s")
            elif secs < 3600:
                meta.append(f"{secs // 60}m")
            else:
                meta.append(f"{secs // 3600}h{(secs % 3600) // 60}m")
        cost = payload.get("cost_usd")
        if cost is not None:
            meta.append(f"${cost:.4f}")
        if meta:
            lines[0] += f"  ({' · '.join(meta)})"

        if inbox_message:
            lines.append("")
            lines.append(inbox_message)

        body = "\n".join(lines)
        issue_number = ref_num

        _gh_api(
            f"/repos/{repo}/issues/{issue_number}/comments",
            self.token, method="POST", body={"body": body},
        )
        logger.info("GitHub: posted run summary for %s on %s #%s", run.id, repo, issue_number)

    def _post_error_comment(self, repo: str, github_ref: str, message: str) -> None:
        """Post an error comment when a flow can't be found."""
        ref_type, _, ref_num = github_ref.partition(":")
        if not ref_num:
            return
        body = f"**llm-flows** error: {message}"
        _gh_api(
            f"/repos/{repo}/issues/{ref_num}/comments",
            self.token, method="POST", body={"body": body},
        )
