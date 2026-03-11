"""Admin CLI commands -- register, project list/delete, db reset."""

import shutil
from pathlib import Path

import click

from ..config import get_repo_root, SYSTEM_DB
from ..db.database import init_db, get_session, reset_engine
from ..defaults import get_defaults_dir
from ..services.project import ProjectService


@click.command("register")
@click.option("--name", "-n", default=None, help="Project name (defaults to directory name)")
def register_cmd(name):
    """Register current repo as a llmflows project."""
    repo_root = get_repo_root()
    if repo_root is None:
        click.echo("Not inside a git repository. Run this from a git repo root.")
        raise SystemExit(1)

    init_db()
    session = get_session()
    try:
        project_svc = ProjectService(session)
        project = project_svc.register(name=name or repo_root.name, path=str(repo_root))

        project_dir = repo_root / ".llmflows"
        project_dir.mkdir(parents=True, exist_ok=True)

        _update_gitignore(repo_root)
        _generate_cursor_rule(repo_root)

        click.echo()
        click.secho("  Project registered", fg="green", bold=True)
        click.echo()
        click.echo(f"  Project:  {click.style(project.name, fg='cyan')}  ({project.id})")
        click.echo(f"  Path:     {click.style(project.path, fg='cyan')}")
        click.echo()
    finally:
        session.close()


def _update_gitignore(repo_root: Path) -> None:
    """Add .worktrees/ to .gitignore if not already present."""
    gitignore = repo_root / ".gitignore"
    pattern = ".worktrees/"

    content = ""
    if gitignore.exists():
        content = gitignore.read_text()

    if pattern not in content:
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"\n{pattern}\n"
        gitignore.write_text(content)


def _generate_cursor_rule(repo_root: Path) -> None:
    """Generate .cursor/rules/llmflows.md from the package default."""
    defaults_dir = get_defaults_dir()
    src = defaults_dir / "llmflows-rule.md"
    if not src.exists():
        return

    dest_dir = repo_root / ".cursor" / "rules"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "llmflows.md"
    shutil.copy2(src, dest)


@click.group()
def db():
    """Database management."""
    pass


@db.command("reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def db_reset(yes):
    """Delete and recreate the llmflows database.

    All projects and tasks will be lost. You will need to run
    'llmflows register' again in each project.
    """
    if not yes:
        click.confirm(
            f"This will delete {SYSTEM_DB} and all data. Continue?",
            abort=True,
        )

    if SYSTEM_DB.exists():
        SYSTEM_DB.unlink()

    reset_engine()
    init_db()

    click.echo()
    click.secho("  Database reset", fg="green", bold=True)
    click.echo()
    click.echo(f"  Run {click.style('llmflows register', fg='yellow')} in your project directories to re-register them.")
    click.echo()


@click.group()
def project():
    """Manage registered projects."""
    pass


@project.command("list")
def project_list():
    """List all registered projects."""
    session = get_session()
    try:
        project_svc = ProjectService(session)
        projects = project_svc.list_all()
        if not projects:
            click.echo("No projects registered. Run 'llmflows register' in a git repo.")
            return
        _render_project_table(projects)
    finally:
        session.close()


def _render_project_table(projects) -> None:
    id_w = 6
    name_w = max((len(p.name) for p in projects), default=4)
    name_w = max(name_w, 4)
    tasks_w = 5

    def header():
        cols = [
            click.style("ID".ljust(id_w), bold=True),
            click.style("NAME".ljust(name_w), bold=True),
            click.style("TASKS".ljust(tasks_w), bold=True),
            click.style("PATH", bold=True),
        ]
        return "  ".join(cols)

    def separator():
        cols = ["─" * id_w, "─" * name_w, "─" * tasks_w, "─" * 40]
        return click.style("  ".join(cols), fg="bright_black")

    click.echo(header())
    click.echo(separator())

    for p in projects:
        task_count = len(p.tasks) if p.tasks else 0
        cols = [
            click.style(p.id.ljust(id_w), fg="white"),
            click.style(p.name.ljust(name_w), fg="cyan"),
            click.style(str(task_count).ljust(tasks_w), fg="yellow"),
            click.style(p.path, fg="bright_black"),
        ]
        click.echo("  ".join(cols))


@project.command("update")
@click.option("--id", "project_id", default=None, help="Project ID (defaults to current repo)")
@click.option("--name", "-n", required=True, help="New project name")
def project_update(project_id, name):
    """Rename a project.

    Example: llmflows project update --name my-app
    """
    session = get_session()
    try:
        project_svc = ProjectService(session)

        if project_id is None:
            p = project_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered project. Use --id to specify.")
                raise SystemExit(1)
            project_id = p.id

        updated = project_svc.update(project_id, name=name)
        if updated:
            click.echo(f"Renamed project {project_id} to {click.style(name, fg='cyan')}")
        else:
            click.echo(f"Project {project_id} not found.")
    finally:
        session.close()


@project.command("delete")
@click.option("--id", "project_id", default=None, help="Project ID to delete (defaults to current repo)")
def project_delete(project_id):
    """Unregister a project."""
    session = get_session()
    try:
        project_svc = ProjectService(session)

        if project_id is None:
            p = project_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered project. Use --id to specify.")
                raise SystemExit(1)
            project_id = p.id

        if project_svc.unregister(project_id):
            click.echo(f"Project {project_id} deleted.")
        else:
            click.echo(f"Project {project_id} not found.")
    finally:
        session.close()
