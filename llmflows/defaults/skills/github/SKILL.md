---
name: github-channel
description: Build flows that integrate with the GitHub channel. Use when the user wants to create a flow triggered by GitHub issues or PR comments, wants to understand what variables the GitHub channel provides, or asks about @llmflows mentions and GitHub integration.
---

# GitHub Channel Integration

The GitHub channel lets users trigger flows by writing `@llmflows:flow-name` in GitHub issues and PR comments. The channel is pure plumbing — it provides context variables and the flow decides what to do with them.

## How it works

1. User writes `@llmflows:feature-develop Add timeout handling` on a GitHub issue or PR
2. The channel polls GitHub, finds the mention, resolves `feature-develop` to a flow in the matching space
3. The text around the mention becomes `TASK_DESCRIPTION`; full issue/PR context is collected
4. A run is enqueued with all context as flow variables
5. When the run completes, the channel posts a summary comment back to the issue/PR

## Available variables

The channel passes these variables to every run. Declare the ones your flow needs in the flow's `variables` section (value can be empty string — the channel fills them at runtime).

### Always provided

| Variable | Example | Description |
|---|---|---|
| `TASK_DESCRIPTION` | `Add timeout handling` | Text from the comment minus the `@llmflows:flow-name` mention |
| `GITHUB_REF` | `issue:42` or `pr:15` | Reference to the source issue or PR |
| `GITHUB_EVENT` | `issue`, `issue_comment`, `pr_comment`, `pr_review` | What triggered the run |

### Issue context (when triggered from an issue or issue comment)

| Variable | Description |
|---|---|
| `ISSUE_NUMBER` | Issue number (e.g. `42`) |
| `ISSUE_TITLE` | Issue title |
| `ISSUE_BODY` | Full issue body text |
| `ISSUE_URL` | GitHub URL to the issue |

### PR context (when triggered from a PR comment or review comment)

| Variable | Description |
|---|---|
| `PR_NUMBER` | PR number |
| `PR_TITLE` | PR title |
| `PR_BODY` | PR description |
| `PR_URL` | GitHub URL to the PR |
| `PR_BRANCH` | Head branch name (e.g. `feat/add-timeout`) |
| `PR_COMMENTS` | All conversation comments on the PR (formatted as `**user**: body`) |
| `PR_REVIEW_COMMENTS` | All inline review comments with file path and line number |

## Flow design patterns

### Issue → worktree → PR (new feature from an issue)

A flow triggered by `@llmflows:feature-develop` on an issue:

**Step 1 — Implement** (code step):
- Derive branch name from issue: `issue-{{flow.ISSUE_NUMBER}}`
- Create worktree: `git worktree add .worktrees/issue-{{flow.ISSUE_NUMBER}} -b issue-{{flow.ISSUE_NUMBER}}`
- Save worktree path to `{{step.dir}}/worktree-path.txt`
- Implement the feature described in `{{flow.TASK_DESCRIPTION}}` and `{{flow.ISSUE_BODY}}`
- Run tests

**Step 2 — Commit and PR** (code step):
- Read worktree path from previous step artifacts
- Commit, push, create PR with `Closes #{{flow.ISSUE_NUMBER}}`
- Write `{{run.dir}}/inbox.md` with summary, PR URL, and `[Open in Cursor](cursor://file/$WORKTREE)` link

Variables to declare: `TASK_DESCRIPTION`, `ISSUE_NUMBER`, `ISSUE_TITLE`, `ISSUE_BODY`, `ISSUE_URL`, `GITHUB_REF`, `GITHUB_EVENT`, `BASE_BRANCH`

### PR follow-up (address review feedback)

A flow triggered by `@llmflows:pr-followup` on a PR comment:

**Step 1 — Address Feedback** (code step):
- Check out the existing branch `{{flow.PR_BRANCH}}` (find or create worktree)
- Pull latest: `git pull origin {{flow.PR_BRANCH}}`
- Read `{{flow.PR_REVIEW_COMMENTS}}` for inline feedback with file paths and line numbers
- Make changes, run tests, commit, push
- Write `{{run.dir}}/inbox.md` with summary and `[Open in Cursor](cursor://file/$WORKTREE)` link

Variables to declare: `TASK_DESCRIPTION`, `PR_NUMBER`, `PR_TITLE`, `PR_BODY`, `PR_URL`, `PR_BRANCH`, `PR_COMMENTS`, `PR_REVIEW_COMMENTS`, `GITHUB_REF`, `GITHUB_EVENT`

### Code review (automated review on new PRs)

A flow triggered by `@llmflows:review` on a PR:

**Step 1 — Review** (code step):
- Check out `{{flow.PR_BRANCH}}`
- Run linters, type checkers, tests
- Read the diff and PR description
- Write review findings to `{{step.dir}}/_result.md`
- Write `{{run.dir}}/inbox.md` with the review summary

### Bug investigation (triage from an issue)

A flow triggered by `@llmflows:investigate` on an issue:

**Step 1 — Investigate** (code step):
- Read `{{flow.ISSUE_BODY}}` for reproduction steps
- Search the codebase for related code
- Try to reproduce the bug
- Write findings and suggested fix to `{{step.dir}}/_result.md` and `{{run.dir}}/inbox.md`

No worktree needed — can run in the space root as a read-only investigation.

## "Open in Cursor" deep link

To let users jump from a notification into Cursor, include this link in `inbox.md`:

```
[Open in Cursor](cursor://file/<absolute-worktree-path>)
```

The flow constructs this from `worktree-path.txt`:

```bash
WORKTREE=$(cat {{step.dir}}/worktree-path.txt)
# Then include in inbox.md:
# [Open in Cursor](cursor://file/$WORKTREE)
```

This link is clickable in Telegram, Slack, and the web UI.

## Channel behaviour

- **Polling-based**: checks GitHub API every 60 seconds (configurable via `poll_interval_seconds`)
- **Deduplication**: skips comments by the bot's own user, skips refs with active runs
- **Auto-mapping**: repos are detected from spaces' `git remote get-url origin` — no per-space config needed
- **Outbound**: posts a summary comment back to the issue/PR when the run completes (uses `inbox_message` from the notification)
- **Error reporting**: if the flow name doesn't exist in the space, posts an error comment on the issue/PR

## Setup

1. Gateway UI → GitHub → set personal access token (needs `repo` scope)
2. Enable the channel
3. Restart gateway (or daemon)
4. Create flows that declare the GitHub variables they need
5. Write `@llmflows:flow-name` on a GitHub issue or PR in any repo that maps to a registered space
