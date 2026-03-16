"""Git worktree management. Uses native `git worktree` commands.

Worktrees are stored in .worktrees/<branch>/ within the repo root.

Per-project configuration is read from ``llmflows.toml`` at the repo root:

    [worktree]
    branch = "main"   # base branch to fetch and branch off; auto-detected when omitted
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _run_git(args: list[str], cwd: Optional[str] = None) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _sanitize_branch(name: str) -> str:
    """Sanitize a branch name for use as a directory name."""
    return re.sub(r"[^\w\-.]", "-", name)


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    if sys.version_info >= (3, 11):
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    try:
        import tomli
        with open(path, "rb") as f:
            return tomli.load(f)
    except ImportError:
        return {}


class WorktreeService:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.worktrees_dir = Path(repo_path) / ".worktrees"

    def _worktree_config(self) -> dict:
        """Return the [worktree] section from llmflows.toml at the project root, or {}."""
        return _read_toml(Path(self.repo_path) / "llmflows.toml").get("worktree", {})

    def _worktree_path_for(self, branch_name: str) -> Path:
        return self.worktrees_dir / _sanitize_branch(branch_name)

    def _detect_default_branch(self) -> str:
        """Detect the default remote branch (main/master/etc)."""
        code, stdout, _ = _run_git(
            ["symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=self.repo_path,
        )
        if code == 0 and stdout.strip():
            return stdout.strip().replace("refs/remotes/origin/", "")
        for branch in ("main", "master"):
            code, _, _ = _run_git(
                ["rev-parse", "--verify", f"origin/{branch}"],
                cwd=self.repo_path,
            )
            if code == 0:
                return branch
        return "master"

    def create(self, branch_name: str) -> tuple[bool, str]:
        """Create a new worktree for *branch_name*.

        Fetches from origin and branches off ``origin/<branch>``.  Falls back
        to the local ref when fetch fails (e.g. no credentials available).

        The base branch is taken from ``[worktree] branch`` in ``llmflows.toml``
        at the project root; auto-detected when omitted.

        Returns (success, message).
        """
        wt_cfg = self._worktree_config()
        base_branch: Optional[str] = wt_cfg.get("branch") or None

        wt_path = self._worktree_path_for(branch_name)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

        branch = base_branch or self._detect_default_branch()
        _run_git(["fetch", "origin", branch], cwd=self.repo_path)

        code, stdout, stderr = _run_git(
            ["worktree", "add", str(wt_path), "-b", branch_name, f"origin/{branch}"],
            cwd=self.repo_path,
        )
        if code == 0:
            return True, stdout.strip() or f"Created worktree at {wt_path}"

        # Fetch may have failed (no credentials) — fall back to local ref
        local_ref = base_branch or "HEAD"
        code, stdout, stderr = _run_git(
            ["worktree", "add", str(wt_path), "-b", branch_name, local_ref],
            cwd=self.repo_path,
        )
        if code == 0:
            return True, stdout.strip() or f"Created worktree at {wt_path} (from local {local_ref})"
        return False, stderr.strip() or stdout.strip()

    def remove(self, branch_name: str) -> tuple[bool, str]:
        """Remove a worktree."""
        wt_path = self.get_worktree_path(branch_name)
        if not wt_path:
            wt_path = self._worktree_path_for(branch_name)

        code, stdout, stderr = _run_git(
            ["worktree", "remove", str(wt_path), "--force"],
            cwd=self.repo_path,
        )
        if code == 0:
            return True, stdout.strip() or f"Removed worktree {wt_path}"
        return False, stderr.strip() or stdout.strip()

    def list(self) -> list[dict[str, str]]:
        """List all worktrees."""
        code, stdout, _ = _run_git(
            ["worktree", "list", "--porcelain"],
            cwd=self.repo_path,
        )
        if code != 0:
            return []

        worktrees = []
        current: dict[str, str] = {}
        for line in stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line[len("worktree "):].strip(), "branch": ""}
            elif line.startswith("branch "):
                ref = line[len("branch "):].strip()
                current["branch"] = ref.replace("refs/heads/", "")
            elif line == "" and current:
                worktrees.append(current)
                current = {}
        if current:
            worktrees.append(current)

        return worktrees

    def get_worktree_path(self, branch_name: str) -> Optional[Path]:
        """Get the filesystem path for a worktree by branch name."""
        for wt in self.list():
            if wt["branch"] == branch_name:
                return Path(wt["path"])

        expected = self._worktree_path_for(branch_name)
        if expected.is_dir():
            return expected

        return None
