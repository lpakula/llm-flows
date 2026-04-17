"""Admin CLI commands -- register, space management."""

from pathlib import Path

import click

from ..config import get_repo_root
from ..db.database import init_db, get_session
from ..services.flow import FlowService
from ..services.space import SpaceService


@click.command("register")
@click.option("--name", "-n", default=None, help="Space name (defaults to directory name)")
def register_cmd(name):
    """Register current directory as a llmflows space."""
    repo_root = get_repo_root()
    space_root = repo_root or Path.cwd()
    git_repo = repo_root is not None

    init_db()
    session = get_session()
    try:
        space_svc = SpaceService(session)
        s = space_svc.register(
            name=name or space_root.name,
            path=str(space_root),
            git_repo=git_repo,
        )

        space_dir = space_root / ".llmflows"
        space_dir.mkdir(parents=True, exist_ok=True)

        if git_repo:
            _update_gitignore(space_root)

        flow_svc = FlowService(session)
        flow_count = flow_svc.sync_from_disk(str(space_root), s.id)

        click.echo()
        click.secho("  Space registered", fg="green", bold=True)
        click.echo()
        click.echo(f"  Space:    {click.style(s.name, fg='cyan')}  ({s.id})")
        click.echo(f"  Path:     {click.style(s.path, fg='cyan')}")
        click.echo(f"  Git repo: {click.style('yes', fg='green') if git_repo else click.style('no', fg='yellow')}")
        if flow_count:
            click.echo(f"  Flows:    {click.style(str(flow_count), fg='cyan')} loaded from flows/")
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
def space():
    """Manage registered spaces."""
    pass


@space.command("list")
def space_list():
    """List all registered spaces."""
    session = get_session()
    try:
        space_svc = SpaceService(session)
        spaces = space_svc.list_all()
        if not spaces:
            click.echo("No spaces registered. Run 'llmflows register' in a directory.")
            return
        _render_space_table(spaces)
    finally:
        session.close()


def _render_space_table(spaces) -> None:
    id_w = 6
    name_w = max((len(s.name) for s in spaces), default=4)
    name_w = max(name_w, 4)

    def header():
        cols = [
            click.style("ID".ljust(id_w), bold=True),
            click.style("NAME".ljust(name_w), bold=True),
            click.style("PATH", bold=True),
        ]
        return "  ".join(cols)

    def separator():
        cols = ["─" * id_w, "─" * name_w, "─" * 40]
        return click.style("  ".join(cols), fg="bright_black")

    click.echo(header())
    click.echo(separator())

    for s in spaces:
        cols = [
            click.style(s.id.ljust(id_w), fg="white"),
            click.style(s.name.ljust(name_w), fg="cyan"),
            click.style(s.path, fg="bright_black"),
        ]
        click.echo("  ".join(cols))


@space.command("update")
@click.option("--id", "space_id", default=None, help="Space ID (defaults to current directory)")
@click.option("--name", "-n", required=True, help="New space name")
def space_update(space_id, name):
    """Rename a space.

    Example: llmflows space update --name my-app
    """
    session = get_session()
    try:
        space_svc = SpaceService(session)

        if space_id is None:
            p = space_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered space. Use --id to specify.")
                raise SystemExit(1)
            space_id = p.id

        updated = space_svc.update(space_id, name=name)
        if updated:
            click.echo(f"Renamed space {space_id} to {click.style(name, fg='cyan')}")
        else:
            click.echo(f"Space {space_id} not found.")
    finally:
        session.close()


@space.command("delete")
@click.option("--id", "space_id", default=None, help="Space ID to delete (defaults to current directory)")
def space_delete(space_id):
    """Unregister a space."""
    session = get_session()
    try:
        space_svc = SpaceService(session)

        if space_id is None:
            p = space_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered space. Use --id to specify.")
                raise SystemExit(1)
            space_id = p.id

        if space_svc.unregister(space_id):
            click.echo(f"Space {space_id} deleted.")
        else:
            click.echo(f"Space {space_id} not found.")
    finally:
        session.close()


@space.group("var")
def space_var():
    """Manage space variables.

    Variables are available in flow step content, gates, and IFs as
    {{space.<KEY>}} template placeholders. Also injected as environment
    variables into the agent runtime.
    """
    pass


@space_var.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--id", "space_id", default=None, help="Space ID (defaults to current directory)")
def var_set(key, value, space_id):
    """Set a space variable.

    \b
    Examples:
      llmflows space var set KM_KUBERNETES_REPOS_PATH /Users/me/repos
      llmflows space var set AGENT_DEFAULT_ORG mycompany
    """
    import json
    session = get_session()
    try:
        space_svc = SpaceService(session)
        if space_id is None:
            p = space_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered space. Use --id to specify.")
                raise SystemExit(1)
            space_id = p.id

        s = space_svc.get(space_id)
        if not s:
            click.echo(f"Space {space_id} not found.")
            raise SystemExit(1)

        variables = s.get_variables()
        variables[key] = value
        space_svc.update(space_id, variables=json.dumps(variables))
        click.echo(f"  {click.style(key, fg='cyan')} = {click.style(value, fg='white')}")
    finally:
        session.close()


@space_var.command("list")
@click.option("--id", "space_id", default=None, help="Space ID (defaults to current directory)")
def var_list(space_id):
    """List all space variables."""
    session = get_session()
    try:
        space_svc = SpaceService(session)
        if space_id is None:
            p = space_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered space. Use --id to specify.")
                raise SystemExit(1)
            space_id = p.id

        s = space_svc.get(space_id)
        if not s:
            click.echo(f"Space {space_id} not found.")
            raise SystemExit(1)

        variables = s.get_variables()
        if not variables:
            click.echo("  No variables set.")
            return

        key_w = max(len(k) for k in variables)
        for k, v in sorted(variables.items()):
            click.echo(f"  {click.style(k.ljust(key_w), fg='cyan')}  {v}")
    finally:
        session.close()


@space_var.command("remove")
@click.argument("key")
@click.option("--id", "space_id", default=None, help="Space ID (defaults to current directory)")
def var_remove(key, space_id):
    """Remove a space variable."""
    import json
    session = get_session()
    try:
        space_svc = SpaceService(session)
        if space_id is None:
            p = space_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered space. Use --id to specify.")
                raise SystemExit(1)
            space_id = p.id

        s = space_svc.get(space_id)
        if not s:
            click.echo(f"Space {space_id} not found.")
            raise SystemExit(1)

        variables = s.get_variables()
        if key not in variables:
            click.echo(f"  Variable '{key}' not found.")
            raise SystemExit(1)

        del variables[key]
        space_svc.update(space_id, variables=json.dumps(variables))
        click.echo(f"  Removed {click.style(key, fg='cyan')}")
    finally:
        session.close()


@space.command("settings")
@click.option("--id", "space_id", default=None, help="Space ID (defaults to current directory)")
@click.option("--git-repo", default=None, type=click.Choice(["true", "false"]),
              help="Mark whether this space is a git repository")
def space_settings(space_id, git_repo):
    """View or update space settings.

    Run with no flags to print current settings.

    Examples:

    \b
      llmflows space settings
      llmflows space settings --git-repo false
    """
    session = get_session()
    try:
        space_svc = SpaceService(session)

        if space_id is None:
            p = space_svc.resolve_current()
            if p is None:
                click.echo("Not inside a registered space. Use --id to specify.")
                raise SystemExit(1)
            space_id = p.id

        s = space_svc.get(space_id)
        if not s:
            click.echo(f"Space {space_id} not found.")
            raise SystemExit(1)

        if git_repo is not None:
            space_svc.update(space_id, is_git_repo=(git_repo == "true"))
            session.refresh(s)

        is_git = s.is_git_repo if s.is_git_repo is not None else True

        click.echo()
        click.echo(f"  Space:     {click.style(s.name, fg='cyan')}  ({s.id})")
        click.echo(f"  Git repo:  {click.style('yes', fg='green') if is_git else click.style('no', fg='yellow')}")
        click.echo()

        if git_repo is not None:
            click.secho("  Settings saved.", fg="green")
            click.echo()
    finally:
        session.close()
