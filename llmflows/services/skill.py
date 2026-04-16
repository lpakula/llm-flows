"""Skill service -- discover skills from disk."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillInfo:
    name: str
    path: str
    description: str
    compatibility: str = ""


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML front-matter key-value pairs from a SKILL.md file."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    meta: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


class SkillService:
    """Discover SKILL.md files from a space's .agents/skills/ directory."""

    SKILLS_DIR = ".agents/skills"
    SKILL_FILE = "SKILL.md"

    @staticmethod
    def discover(project_path: str) -> list[SkillInfo]:
        """Scan .agents/skills/ and return info for each skill found."""
        skills_root = Path(project_path) / SkillService.SKILLS_DIR
        if not skills_root.is_dir():
            return []

        results = []
        for skill_dir in sorted(skills_root.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / SkillService.SKILL_FILE
            if not skill_file.is_file():
                continue

            description = ""
            compatibility = ""
            try:
                text = skill_file.read_text(errors="replace")
                meta = _parse_frontmatter(text)
                description = meta.get("description", "")
                compatibility = meta.get("compatibility", "")
                if not description:
                    for line in text.splitlines():
                        stripped = line.strip()
                        if stripped and not stripped.startswith("---"):
                            description = stripped.lstrip("#").strip()
                            break
            except (OSError, PermissionError):
                pass

            results.append(SkillInfo(
                name=skill_dir.name,
                path=str(skill_file),
                description=description,
                compatibility=compatibility,
            ))
        return results

    @staticmethod
    def get_content(project_path: str, skill_name: str) -> str | None:
        """Read the full content of a skill's SKILL.md file."""
        skill_file = Path(project_path) / SkillService.SKILLS_DIR / skill_name / SkillService.SKILL_FILE
        if not skill_file.is_file():
            return None
        try:
            return skill_file.read_text(errors="replace")
        except (OSError, PermissionError):
            return None

    @staticmethod
    def resolve_skills(project_path: str, skill_names: list[str]) -> list[SkillInfo]:
        """Resolve a list of skill names to SkillInfo objects."""
        all_skills = {s.name: s for s in SkillService.discover(project_path)}
        return [all_skills[n] for n in skill_names if n in all_skills]
