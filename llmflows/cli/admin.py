"""Admin CLI commands -- register, project list/delete, db reset."""

from pathlib import Path

import click

from ..config import get_repo_root, SYSTEM_DB
from ..db.database import init_db, get_session, reset_engine
from ..services.project import ProjectService


@click.command("register")
@click.option("--name", "-n", default=None, help="Project name (defaults to directory name)")
def register_cmd(name):
    """Register current directory as a llmflows project."""
    repo_root = get_repo_root()
    project_root = repo_root or Path.cwd()
    git_repo = repo_root is not None

    init_db()
    session = get_session()
    try:
        project_svc = ProjectService(session)
        project = project_svc.register(
            name=name or project_root.name,
            path=str(project_root),
            git_repo=git_repo,
        )

        project_dir = project_root / ".llmflows"
        project_dir.mkdir(parents=True, exist_ok=True)

        if git_repo:
            _update_gitignore(project_root)

        click.echo()
        click.secho("  Project registered", fg="green", bold=True)
        click.echo()
        click.echo(f"  Project:  {click.style(project.name, fg='cyan')}  ({project.id})")
        click.echo(f"  Path:     {click.style(project.path, fg='cyan')}")
        click.echo(f"  Git repo: {click.style('yes', fg='green') if git_repo else click.style('no', fg='yellow')}")
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


@click.group()
def db():
    """Database management."""
    pass


@db.group("migrate")
def db_migrate():
    """Manage database schema migrations (powered by Alembic)."""
    pass


@db_migrate.command("upgrade")
def migrate_upgrade():
    """Apply all pending migrations to bring the DB up to date."""
    from alembic import command as alembic
    from ..db.database import init_db, _alembic_cfg
    from ..config import SYSTEM_DB

    init_db()
    alembic.upgrade(_alembic_cfg(f"sqlite:///{SYSTEM_DB}"), "head")
    click.secho("Database is up to date.", fg="green")


@db_migrate.command("current")
def migrate_current():
    """Show the current migration revision."""
    from alembic import command as alembic
    from ..db.database import _alembic_cfg
    from ..config import SYSTEM_DB

    alembic.current(_alembic_cfg(f"sqlite:///{SYSTEM_DB}"), verbose=True)


@db_migrate.command("history")
def migrate_history():
    """Show the full migration history."""
    from alembic import command as alembic
    from ..db.database import _alembic_cfg
    from ..config import SYSTEM_DB

    alembic.history(_alembic_cfg(f"sqlite:///{SYSTEM_DB}"), verbose=True)


@db_migrate.command("create")
@click.argument("message")
@click.option("--no-autogenerate", is_flag=True, default=False,
              help="Create an empty migration instead of auto-detecting schema changes")
def migrate_create(message, no_autogenerate):
    """Generate a new migration file.

    Compares the current DB against the ORM models and writes the diff.

    Example:

      llmflows db migrate create "add tags column to tasks"
    """
    from alembic import command as alembic
    from ..db.database import init_db, _alembic_cfg
    from ..config import SYSTEM_DB

    init_db()
    alembic.revision(
        _alembic_cfg(f"sqlite:///{SYSTEM_DB}"),
        message=message,
        autogenerate=not no_autogenerate,
    )


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


@project.group("var")
def project_var():
    """Manage project variables.

    Variables are available in flow step content, gates, and IFs as
    {{project.<KEY>}} template placeholders. Also injected as environment
    variables into the agent runtime.
    """
    pass


@project_var.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--id", "project_id", default=None, help="Project ID (defaults to current repo)")
def var_set(key, value, project_id):
    """Set a project variable.

    \b
    Examples:
      llmflows project var set KM_KUBERNETES_REPOS_PATH /Users/me/repos
      llmflows project var set AGENT_DEFAULT_ORG mycompany
    """
    import json
    session = get_session()
    try:
        project_svc = ProjectService(session)
        if project_id is None:
            p = project_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered project. Use --id to specify.")
                raise SystemExit(1)
            project_id = p.id

        project = project_svc.get(project_id)
        if not project:
            click.echo(f"Project {project_id} not found.")
            raise SystemExit(1)

        variables = project.get_variables()
        variables[key] = value
        project_svc.update(project_id, variables=json.dumps(variables))
        click.echo(f"  {click.style(key, fg='cyan')} = {click.style(value, fg='white')}")
    finally:
        session.close()


@project_var.command("list")
@click.option("--id", "project_id", default=None, help="Project ID (defaults to current repo)")
def var_list(project_id):
    """List all project variables."""
    session = get_session()
    try:
        project_svc = ProjectService(session)
        if project_id is None:
            p = project_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered project. Use --id to specify.")
                raise SystemExit(1)
            project_id = p.id

        project = project_svc.get(project_id)
        if not project:
            click.echo(f"Project {project_id} not found.")
            raise SystemExit(1)

        variables = project.get_variables()
        if not variables:
            click.echo("  No variables set.")
            return

        key_w = max(len(k) for k in variables)
        for k, v in sorted(variables.items()):
            click.echo(f"  {click.style(k.ljust(key_w), fg='cyan')}  {v}")
    finally:
        session.close()


@project_var.command("remove")
@click.argument("key")
@click.option("--id", "project_id", default=None, help="Project ID (defaults to current repo)")
def var_remove(key, project_id):
    """Remove a project variable."""
    import json
    session = get_session()
    try:
        project_svc = ProjectService(session)
        if project_id is None:
            p = project_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered project. Use --id to specify.")
                raise SystemExit(1)
            project_id = p.id

        project = project_svc.get(project_id)
        if not project:
            click.echo(f"Project {project_id} not found.")
            raise SystemExit(1)

        variables = project.get_variables()
        if key not in variables:
            click.echo(f"  Variable '{key}' not found.")
            raise SystemExit(1)

        del variables[key]
        project_svc.update(project_id, variables=json.dumps(variables))
        click.echo(f"  Removed {click.style(key, fg='cyan')}")
    finally:
        session.close()


@project.command("settings")
@click.option("--id", "project_id", default=None, help="Project ID (defaults to current repo)")
@click.option("--git-repo", default=None, type=click.Choice(["true", "false"]),
              help="Mark whether this project is a git repository")
def project_settings(project_id, git_repo):
    """View or update project settings.

    Run with no flags to print current settings.

    Examples:

    \b
      llmflows project settings
      llmflows project settings --git-repo false
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

        project = project_svc.get(project_id)
        if not project:
            click.echo(f"Project {project_id} not found.")
            raise SystemExit(1)

        if git_repo is not None:
            project_svc.update(project_id, is_git_repo=(git_repo == "true"))
            session.refresh(project)

        is_git = project.is_git_repo if project.is_git_repo is not None else True

        click.echo()
        click.echo(f"  Project:   {click.style(project.name, fg='cyan')}  ({project.id})")
        click.echo(f"  Git repo:  {click.style('yes', fg='green') if is_git else click.style('no', fg='yellow')}")
        click.echo()

        if git_repo is not None:
            click.secho("  Settings saved.", fg="green")
            click.echo()
    finally:
        session.close()
