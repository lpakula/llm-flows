"""Upgrade CLI command -- pull latest version and restart services."""

import click


@click.command("upgrade")
def upgrade():
    """Upgrade llmflows to the latest version and restart services."""
    from ..services.upgrade import (
        pip_upgrade,
        kill_ui_processes,
        restart_daemon_via_cli,
        start_ui_background,
    )

    click.echo("Upgrading llmflows…")
    success, old_ver, new_ver, output = pip_upgrade()
    if not success:
        click.echo(f"Upgrade failed:\n{output}", err=True)
        raise SystemExit(1)

    if old_ver == new_ver:
        click.echo(f"Already at latest version ({old_ver})")
    else:
        click.echo(f"Upgraded: {old_ver} → {new_ver}")

    ui_killed = kill_ui_processes()
    if ui_killed:
        click.echo(f"Stopped UI (pids: {ui_killed})")

    click.echo("Restarting daemon…")
    ok, msg = restart_daemon_via_cli()
    if ok:
        click.echo(f"  {msg}")
    else:
        click.echo(f"  Daemon restart failed: {msg}", err=True)

    if ui_killed:
        click.echo("Restarting UI…")
        pid = start_ui_background()
        if pid:
            click.echo(f"  UI started (pid {pid})")
        else:
            click.echo("  Failed to restart UI — run `llmflows ui` manually.", err=True)

    click.echo("Upgrade complete.")
