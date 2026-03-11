"""Git utilities for generating LLM-optimized diffs."""

import subprocess
from typing import Optional


def _run_git(args: list[str], cwd: str = ".") -> Optional[str]:
    """Run git command and return output, or None on error."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


def truncate_patch(patch: str, max_lines_per_file: int = 50) -> str:
    """Truncate per-file diffs to avoid context overload.

    - Deleted files: summary line instead of full content
    - Renamed files with no changes: summary line
    - Large diffs: summary with line count
    """
    if not patch:
        return ""

    lines = patch.splitlines()
    result: list[str] = []
    current_file_start: Optional[int] = None
    current_filename: Optional[str] = None
    in_file = False

    def extract_filename(diff_line: str) -> str:
        parts = diff_line.split(" b/")
        return parts[-1] if len(parts) > 1 else diff_line

    def is_deleted_file(file_content: list[str]) -> bool:
        for line in file_content[1:]:
            if line.startswith("deleted file mode"):
                return True
            if line.startswith("@@"):
                break
        return False

    def is_rename_only(file_content: list[str]) -> tuple[bool, Optional[str]]:
        old_name = None
        has_rename = False
        has_hunks = False
        for line in file_content[1:]:
            if line.startswith("rename from "):
                old_name = line.replace("rename from ", "").strip()
                has_rename = True
            if line.startswith("@@"):
                has_hunks = True
                break
        return (has_rename and not has_hunks, old_name)

    def process_file(file_content: list[str], filename: str) -> None:
        if is_deleted_file(file_content):
            result.append(f"D  {filename}")
            return

        rename_only, old_name = is_rename_only(file_content)
        if rename_only and old_name:
            result.append(f"R  {old_name} -> {filename}")
            return

        if len(file_content) > max_lines_per_file:
            result.append(f"M  [{len(file_content)} lines] {filename}")
            return

        result.extend(file_content)

    for i, line in enumerate(lines):
        if line.startswith("diff --git "):
            if in_file and current_file_start is not None:
                file_content = lines[current_file_start:i]
                process_file(file_content, current_filename or "unknown")
            current_file_start = i
            current_filename = extract_filename(line)
            in_file = True

    if in_file and current_file_start is not None:
        file_content = lines[current_file_start:]
        process_file(file_content, current_filename or "unknown")

    return "\n".join(result) if result else patch


def get_worktree_diff(base: str = "main", cwd: str = ".") -> str:
    """Get the diff between base branch and current HEAD, truncated for LLM context."""
    output = _run_git(["diff", f"{base}...HEAD", "--unified=3", "-M", "-C"], cwd)
    if not output or not output.strip():
        output = _run_git(["diff", base, "--unified=3", "-M", "-C"], cwd)
    if not output or not output.strip():
        return ""
    return truncate_patch(output.strip())
