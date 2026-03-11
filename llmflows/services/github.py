"""GitHub integration -- polls issue comments for @llmflows triggers."""

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..config import KNOWN_AGENTS, KNOWN_MODELS
from ..db.models import Integration, Task, TaskType

logger = logging.getLogger("llmflows.github")

API_BASE = "https://api.github.com"


class GitHubService:
    def __init__(self, token: str):
        self.client = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def close(self):
        self.client.close()

    # -- API helpers --

    def _get(self, path: str, **params) -> httpx.Response:
        resp = self.client.get(path, params=params)
        resp.raise_for_status()
        return resp

    def _post(self, path: str, json_data: dict) -> httpx.Response:
        resp = self.client.post(path, json=json_data)
        resp.raise_for_status()
        return resp

    # -- Repo detection --

    @staticmethod
    def get_repo_from_remote(project_path: str) -> Optional[str]:
        """Extract owner/repo from git remote origin URL."""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return None
            url = result.stdout.strip()
        except FileNotFoundError:
            return None

        # SSH: git@github.com:owner/repo.git
        m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
        # HTTPS: https://github.com/owner/repo.git
        m = re.match(r"https://github\.com/(.+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
        return None

    # -- @llmflows command parsing --

    @staticmethod
    def parse_mr_command(body: str) -> Optional[dict]:
        """Parse a @llmflows trigger from a comment body.

        Returns None if no @llmflows found.
        Returns {"model": str|None, "flow_chain": list[str]|None, "agent": str|None,
                 "alias": str|None}.
        """
        match = re.search(r"@llmflows\b(.*?)(?:\n|$)", body)
        if not match:
            return None

        args_str = match.group(1).strip()
        result: dict = {"model": None, "flow_chain": None, "agent": None, "alias": None}
        if not args_str:
            return result

        parts = re.split(r"\s+", args_str)
        i = 0
        while i < len(parts):
            if parts[i] == "--model" and i + 1 < len(parts):
                result["model"] = parts[i + 1]
                i += 2
            elif parts[i] == "--flow" and i + 1 < len(parts):
                result["flow_chain"] = [f.strip() for f in parts[i + 1].split(",") if f.strip()]
                i += 2
            elif parts[i] == "--agent" and i + 1 < len(parts):
                result["agent"] = parts[i + 1]
                i += 2
            elif parts[i] == "--alias" and i + 1 < len(parts):
                result["alias"] = parts[i + 1]
                i += 2
            else:
                i += 1

        return result

    # -- GitHub API operations --

    def get_issue(self, repo: str, issue_number: int) -> dict:
        return self._get(f"/repos/{repo}/issues/{issue_number}").json()

    def get_issue_comments(self, repo: str, since: Optional[str] = None) -> list[dict]:
        params = {"sort": "created", "direction": "asc", "per_page": 100}
        if since:
            params["since"] = since
        return self._get(f"/repos/{repo}/issues/comments", **params).json()

    def add_reaction(self, repo: str, comment_id: int, reaction: str = "eyes") -> bool:
        try:
            self._post(
                f"/repos/{repo}/issues/comments/{comment_id}/reactions",
                {"content": reaction},
            )
            return True
        except httpx.HTTPStatusError:
            return False

    def has_reaction(self, repo: str, comment_id: int, reaction: str = "eyes") -> bool:
        """Check if a comment already has a specific reaction from the authenticated user."""
        try:
            resp = self._get(f"/repos/{repo}/issues/comments/{comment_id}/reactions")
            user_resp = self._get("/user")
            my_login = user_resp.json().get("login", "")
            for r in resp.json():
                if r.get("content") == reaction and r.get("user", {}).get("login") == my_login:
                    return True
        except httpx.HTTPStatusError:
            pass
        return False

    def comment_on_issue(self, repo: str, issue_number: int, body: str) -> Optional[dict]:
        try:
            resp = self._post(f"/repos/{repo}/issues/{issue_number}/comments", {"body": body})
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("Failed to comment on issue #%d: %s", issue_number, e)
            return None

    def find_pr_for_branch(self, repo: str, branch: str) -> Optional[dict]:
        """Find an open PR for a branch."""
        try:
            resp = self._get(f"/repos/{repo}/pulls", state="open", head=f"{repo.split('/')[0]}:{branch}")
            prs = resp.json()
            return prs[0] if prs else None
        except httpx.HTTPStatusError:
            return None

    def comment_on_pr(self, repo: str, pr_number: int, body: str) -> Optional[dict]:
        return self.comment_on_issue(repo, pr_number, body)

    # -- Polling --

    def poll_integration(self, integration: Integration, session) -> int:
        """Poll a GitHub integration for @llmflows comments. Returns count of tasks created/updated."""
        from .flow import FlowService
        from .run import RunService
        from .task import TaskService

        config = integration.get_config()
        repo = config.get("repo", "")
        if not repo:
            logger.warning("Integration %s has no repo configured", integration.id)
            return 0

        since = None
        if integration.last_polled_at:
            since = integration.last_polled_at.isoformat() + "Z"

        try:
            comments = self.get_issue_comments(repo, since=since)
        except httpx.HTTPStatusError as e:
            logger.error("Failed to fetch comments for %s: %s", repo, e)
            return 0

        task_svc = TaskService(session)
        run_svc = RunService(session)
        flow_svc = FlowService(session)
        project = integration.project
        count = 0

        for comment in comments:
            mr_cmd = self.parse_mr_command(comment.get("body", ""))
            if not mr_cmd:
                continue

            comment_id = comment["id"]

            if self.has_reaction(repo, comment_id, "eyes"):
                continue

            # Extract issue number from the issue_url
            issue_url = comment.get("issue_url", "")
            issue_match = re.search(r"/issues/(\d+)$", issue_url)
            if not issue_match:
                continue
            issue_number = int(issue_match.group(1))

            # Resolve alias (falls back to "default"), then explicit flags override
            alias_name = mr_cmd.get("alias") or "default"
            alias_config = project.get_alias(alias_name)
            if not alias_config:
                available = ", ".join(f"`{a}`" for a in project.get_aliases())
                self.add_reaction(repo, comment_id, "eyes")
                self.comment_on_issue(
                    repo, issue_number,
                    f"Unknown alias `{alias_name}`. Available aliases: {available}",
                )
                continue

            model = mr_cmd["model"] or alias_config.get("model") or "auto"
            agent = mr_cmd["agent"] or alias_config.get("agent") or "cursor"
            flow_chain = mr_cmd["flow_chain"] or alias_config.get("flow_chain") or ["default"]

            # Validate agent
            if agent not in KNOWN_AGENTS:
                self.add_reaction(repo, comment_id, "eyes")
                self.comment_on_issue(
                    repo, issue_number,
                    f"Unknown agent `{agent}`. Available agents: {', '.join(KNOWN_AGENTS)}",
                )
                continue

            # Validate model
            if model and model not in KNOWN_MODELS:
                self.add_reaction(repo, comment_id, "eyes")
                self.comment_on_issue(
                    repo, issue_number,
                    f"Unknown model `{model}`. Available models: {', '.join(KNOWN_MODELS)}",
                )
                continue

            # Validate flows
            invalid_flows = []
            for flow_name in flow_chain:
                if not flow_svc.get_by_name(flow_name):
                    invalid_flows.append(flow_name)
            if invalid_flows:
                all_flows = [f.name for f in flow_svc.list_all()]
                self.add_reaction(repo, comment_id, "eyes")
                self.comment_on_issue(
                    repo, issue_number,
                    f"Unknown flow(s): {', '.join(f'`{f}`' for f in invalid_flows)}. "
                    f"Available flows: {', '.join(all_flows)}",
                )
                continue

            # Find or create task for this issue
            existing_task = (
                session.query(Task)
                .filter_by(project_id=project.id, github_issue_number=issue_number)
                .first()
            )

            if existing_task:
                task = existing_task
                task.github_comment_id = comment_id
                session.commit()
            else:
                try:
                    issue_data = self.get_issue(repo, issue_number)
                except httpx.HTTPStatusError:
                    issue_data = {}

                task = task_svc.create(
                    project_id=project.id,
                    name=issue_data.get("title", f"Issue #{issue_number}"),
                    description=issue_data.get("body", "") or "",
                    task_type=TaskType.CHORE,
                )
                task.integration_id = integration.id
                task.github_issue_number = issue_number
                task.github_comment_id = comment_id
                session.commit()

            # Determine prompt: first run uses issue description, subsequent runs
            # use the text from the @llmflows comment (excluding the command itself)
            is_first_run = not existing_task
            if is_first_run:
                user_prompt = task.description
            else:
                raw_body = comment.get("body", "")
                user_prompt = re.sub(r"@llmflows\b[^\n]*", "", raw_body).strip()

            if not user_prompt:
                self.add_reaction(repo, comment_id, "eyes")
                self.comment_on_issue(
                    repo, issue_number,
                    "No prompt provided. Please describe the task in the issue body "
                    "or include instructions after `@llmflows`, e.g. `@llmflows fix the login form`.",
                )
                continue

            run_svc.enqueue(
                project_id=project.id,
                task_id=task.id,
                flow_name=flow_chain[0],
                flow_chain=flow_chain,
                model=model,
                agent=agent,
                user_prompt=user_prompt,
            )

            self.add_reaction(repo, comment_id, "eyes")
            count += 1
            logger.info(
                "Created run for issue #%d (task %s) in %s",
                issue_number, task.id, repo,
            )

        integration.last_polled_at = datetime.now(timezone.utc)
        session.commit()

        return count

    def post_run_result(self, repo: str, task: Task, run_id: str,
                        summary: str, branch: str) -> None:
        """Post run result back to the GitHub issue and add PR backlink if applicable."""
        if not task.github_issue_number:
            return

        issue_number = task.github_issue_number
        pr = self.find_pr_for_branch(repo, branch) if branch else None

        if pr:
            pr_number = pr["number"]
            self.comment_on_issue(
                repo, issue_number,
                f"llmflows completed run `{run_id}`. PR: #{pr_number}",
            )
            # Add backlink on PR (only if no prior llmflows comment exists)
            self.comment_on_pr(
                repo, pr_number,
                f"Created by llmflows from #{issue_number}",
            )
        else:
            short_summary = (summary[:200] + "...") if len(summary) > 200 else summary
            self.comment_on_issue(
                repo, issue_number,
                f"llmflows completed run `{run_id}`.\n\n{short_summary}" if short_summary
                else f"llmflows completed run `{run_id}`.",
            )
