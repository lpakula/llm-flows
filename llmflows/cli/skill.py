"""Skill CLI commands — list, search, add, and remove skills."""

import click

from ..config import get_repo_root
from ..services.skill import SkillService
from ..services.skillssh import SkillsShService, parse_skill_ref


def _resolve_space_path(space_id: str | None) -> str:
    """Resolve the project path from --space or current directory."""
    if space_id:
        from ..db.database import get_session
        from ..services.space import SpaceService
        session = get_session()
        try:
            svc = SpaceService(session)
            space = svc.get(space_id)
            if not space:
                click.echo(f"Space '{space_id}' not found.")
                raise SystemExit(1)
            return space.path
        finally:
            session.close()
    root = get_repo_root()
    if root:
        return str(root)
    import os
    return os.getcwd()


@click.group("skill")
def skill():
    """Manage agent skills — list, search, add, and remove."""
    pass


@skill.command("list")
@click.option("--space", "space_id", default=None, help="Space ID (defaults to current directory)")
def skill_list(space_id):
    """List installed skills."""
    project_path = _resolve_space_path(space_id)
    skills = SkillsShService.list_with_sources(project_path)

    if not skills:
        click.echo("No skills found in .agents/skills/")
        click.echo("  Install from skills.sh: llmflows skill add owner/repo@skill-name")
        return

    name_w = max(len(s["name"]) for s in skills)
    name_w = max(name_w, 4)

    cols = [
        click.style("NAME".ljust(name_w), bold=True),
        click.style("SOURCE".ljust(30), bold=True),
        click.style("DESCRIPTION", bold=True),
    ]
    click.echo("  ".join(cols))
    click.echo(click.style("  ".join(["─" * name_w, "─" * 30, "─" * 40]), fg="bright_black"))

    for s in skills:
        source = ""
        if s["source"]:
            source = click.style(s["source"].get("slug", "skills.sh"), fg="blue")
        else:
            source = click.style("local", fg="bright_black")

        desc = s["description"][:40] if s["description"] else ""
        cols = [
            click.style(s["name"].ljust(name_w), fg="cyan"),
            source.ljust(39),
            click.style(desc, fg="bright_black"),
        ]
        click.echo("  ".join(cols))


@skill.command("add")
@click.argument("source")
@click.option("--space", "space_id", default=None, help="Space ID (defaults to current directory)")
def skill_add(source, space_id):
    """Install a skill from skills.sh.

    \b
    SOURCE is in the format owner/repo@skill-name.

    \b
    Examples:
      llmflows skill add microsoft/azure-skills@azure-ai
      llmflows skill add pbakaus/impeccable@impeccable
    """
    project_path = _resolve_space_path(space_id)

    parsed = parse_skill_ref(source)
    if not parsed:
        click.echo(f"Invalid skill reference: {source}")
        click.echo("Use format: owner/repo@skill-name")
        raise SystemExit(1)

    owner, repo, skill_name = parsed
    click.echo(f"  Installing {click.style(skill_name, fg='cyan')} from {click.style(f'{owner}/{repo}', fg='blue')}...")

    result = SkillsShService.install(project_path, owner, repo, skill_name)

    if result.success:
        click.echo()
        click.secho("  Installed", fg="green", bold=True)
        click.echo(f"  Skill:  {click.style(result.skill_name, fg='cyan')}")
        click.echo(f"  Path:   {click.style(result.path, fg='bright_black')}")
        click.echo()
    else:
        click.echo()
        click.secho(f"  Failed: {result.error}", fg="red")
        raise SystemExit(1)


@skill.command("search")
@click.argument("query")
@click.option("--limit", "-l", default=10, help="Maximum results to show")
def skill_search(query, limit):
    """Search for skills on skills.sh / GitHub.

    \b
    Examples:
      llmflows skill search testing
      llmflows skill search "react best practices"
    """
    click.echo(f"  Searching for '{click.style(query, fg='cyan')}'...\n")

    results = SkillsShService.search_github(query, limit=limit)

    if not results:
        click.echo("  No skills found. Try a different query.")
        return

    for s in results:
        installs = ""
        if s.install_count > 0:
            installs = click.style(f"  ({s.install_count:,} installs)", fg="bright_black")
        click.echo(f"  {click.style(s.slug, fg='cyan')}{installs}")
        if s.description:
            click.echo(click.style(f"    {s.description}", fg="bright_black"))

    click.echo()
    click.echo(f"  Install with: llmflows skill add {click.style('<owner/repo@skill>', fg='cyan')}")


@skill.command("remove")
@click.argument("name")
@click.option("--space", "space_id", default=None, help="Space ID (defaults to current directory)")
def skill_remove(name, space_id):
    """Remove an installed skill.

    \b
    Example: llmflows skill remove azure-ai
    """
    project_path = _resolve_space_path(space_id)

    if SkillsShService.remove(project_path, name):
        click.echo(f"  Removed {click.style(name, fg='cyan')}")
    else:
        click.echo(f"  Skill '{name}' not found.")
        raise SystemExit(1)


@skill.command("info")
@click.argument("name")
@click.option("--space", "space_id", default=None, help="Space ID (defaults to current directory)")
def skill_info(name, space_id):
    """Show details about an installed skill."""
    project_path = _resolve_space_path(space_id)

    content = SkillService.get_content(project_path, name)
    if content is None:
        click.echo(f"  Skill '{name}' not found.")
        raise SystemExit(1)

    source = SkillsShService.get_source_info(project_path, name)

    click.echo()
    click.echo(f"  Skill:   {click.style(name, fg='cyan')}")
    if source:
        click.echo(f"  Source:  {click.style(source.get('slug', ''), fg='blue')}")
    click.echo(f"  Path:    {click.style(f'.agents/skills/{name}/SKILL.md', fg='bright_black')}")
    click.echo()

    lines = content.split("\n")[:20]
    for line in lines:
        click.echo(f"  {line}")
    if len(content.split("\n")) > 20:
        click.echo(click.style("  ... (truncated)", fg="bright_black"))
    click.echo()
