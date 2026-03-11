"""Git worktree management. Uses native `git worktree` commands.

Worktrees are stored in .worktrees/<branch>/ within the repo root.
"""

import re
import subprocess
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


class WorktreeService:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.worktrees_dir = Path(repo_path) / ".worktrees"

    def _worktree_path_for(self, branch_name: str) -> Path:
        return self.worktrees_dir / _sanitize_branch(branch_name)

    def create(self, branch_name: str) -> tuple[bool, str]:
        """Create a new worktree with a new branch off the latest origin/main.

        Fetches origin first so the worktree always starts from the newest
        remote main, regardless of the local branch state.

        Returns (success, message).
        """
        wt_path = self._worktree_path_for(branch_name)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

        _run_git(["fetch", "origin", "main"], cwd=self.repo_path)

        code, stdout, stderr = _run_git(
            ["worktree", "add", str(wt_path), "-b", branch_name, "origin/main"],
            cwd=self.repo_path,
        )
        if code == 0:
            return True, stdout.strip() or f"Created worktree at {wt_path}"
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
