"""Skills.sh registry client — search, fetch, and install skills from skills.sh."""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

from .skill import SkillService, SkillInfo, _parse_frontmatter

GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 15


@dataclass
class RegistrySkill:
    """A skill available on skills.sh (GitHub-backed)."""

    name: str
    owner: str
    repo: str
    description: str = ""
    install_count: int = 0
    source: str = ""

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}@{self.name}"

    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


@dataclass
class InstallResult:
    success: bool
    skill_name: str
    path: str = ""
    error: str = ""


_SKILL_REF_RE = re.compile(
    r"^(?P<owner>[a-zA-Z0-9_.-]+)/(?P<repo>[a-zA-Z0-9_.-]+)[@/](?P<skill>[a-zA-Z0-9_.-]+)$"
)


def parse_skill_ref(ref: str) -> tuple[str, str, str] | None:
    """Parse 'owner/repo@skill' or 'owner/repo/skill' into (owner, repo, skill)."""
    m = _SKILL_REF_RE.match(ref.strip())
    if not m:
        return None
    return m.group("owner"), m.group("repo"), m.group("skill")


def _http_get(url: str, *, accept: str = "application/json") -> bytes | None:
    """Simple HTTP GET with timeout. Returns None on failure."""
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "llmflows"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


class SkillsShService:
    """Interact with skills.sh / GitHub to search, preview, and install skills."""

    @staticmethod
    def fetch_skill_md(owner: str, repo: str, skill: str, branch: str = "main") -> str | None:
        """Fetch a SKILL.md from GitHub raw content."""
        for path_pattern in [
            f"{owner}/{repo}/{branch}/{skill}/SKILL.md",
            f"{owner}/{repo}/{branch}/.cursor/skills/{skill}/SKILL.md",
            f"{owner}/{repo}/{branch}/.agents/skills/{skill}/SKILL.md",
            f"{owner}/{repo}/{branch}/skills/{skill}/SKILL.md",
        ]:
            url = f"{GITHUB_RAW}/{path_pattern}"
            data = _http_get(url, accept="text/plain")
            if data:
                return data.decode("utf-8", errors="replace")
        return None

    @staticmethod
    def install(project_path: str, owner: str, repo: str, skill: str) -> InstallResult:
        """Install a skill from GitHub into the project's .agents/skills/ directory."""
        content = SkillsShService.fetch_skill_md(owner, repo, skill)
        if content is None:
            return InstallResult(
                success=False,
                skill_name=skill,
                error=f"Could not fetch SKILL.md from {owner}/{repo} for skill '{skill}'",
            )

        skills_dir = Path(project_path) / SkillService.SKILLS_DIR / skill
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skills_dir / SkillService.SKILL_FILE
        skill_file.write_text(content)

        source_file = skills_dir / ".source"
        source_file.write_text(json.dumps({
            "registry": "skills.sh",
            "owner": owner,
            "repo": repo,
            "skill": skill,
            "slug": f"{owner}/{repo}@{skill}",
        }))

        return InstallResult(
            success=True,
            skill_name=skill,
            path=str(skill_file.relative_to(project_path)),
        )

    @staticmethod
    def install_from_ref(project_path: str, ref: str) -> InstallResult:
        """Install a skill from a reference string like 'owner/repo@skill'."""
        parsed = parse_skill_ref(ref)
        if not parsed:
            return InstallResult(
                success=False, skill_name=ref,
                error=f"Invalid skill reference '{ref}'. Use format: owner/repo@skill-name",
            )
        owner, repo, skill = parsed
        return SkillsShService.install(project_path, owner, repo, skill)

    @staticmethod
    def search_github(query: str, limit: int = 20) -> list[RegistrySkill]:
        """Search GitHub for skill repositories containing SKILL.md files."""
        q = urllib.request.quote(f"{query} SKILL.md in:path")
        url = f"{GITHUB_API}/search/code?q={q}&per_page={limit}"
        data = _http_get(url)
        if not data:
            return []

        try:
            results = json.loads(data)
        except json.JSONDecodeError:
            return []

        seen: dict[str, RegistrySkill] = {}
        for item in results.get("items", []):
            repo_info = item.get("repository", {})
            owner = repo_info.get("owner", {}).get("login", "")
            repo = repo_info.get("name", "")
            path = item.get("path", "")

            parts = path.replace("SKILL.md", "").strip("/").split("/")
            skill_name = parts[-1] if parts and parts[-1] else repo

            slug = f"{owner}/{repo}@{skill_name}"
            if slug not in seen and owner and repo and skill_name:
                seen[slug] = RegistrySkill(
                    name=skill_name,
                    owner=owner,
                    repo=repo,
                    description=repo_info.get("description", ""),
                    source=slug,
                )

        return list(seen.values())[:limit]

    @staticmethod
    def get_source_info(project_path: str, skill_name: str) -> dict | None:
        """Read the .source metadata for an installed skill, if present."""
        source_file = Path(project_path) / SkillService.SKILLS_DIR / skill_name / ".source"
        if not source_file.is_file():
            return None
        try:
            return json.loads(source_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def list_with_sources(project_path: str) -> list[dict]:
        """List installed skills with source metadata for those from skills.sh."""
        skills = SkillService.discover(project_path)
        result = []
        for s in skills:
            entry = {
                "name": s.name,
                "path": s.path,
                "description": s.description,
                "compatibility": s.compatibility,
                "source": None,
            }
            src = SkillsShService.get_source_info(project_path, s.name)
            if src:
                entry["source"] = src
            result.append(entry)
        return result

    @staticmethod
    def remove(project_path: str, skill_name: str) -> bool:
        """Remove an installed skill directory."""
        skill_dir = Path(project_path) / SkillService.SKILLS_DIR / skill_name
        if not skill_dir.is_dir():
            return False
        import shutil
        shutil.rmtree(skill_dir)
        return True
