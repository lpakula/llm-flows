"""UI CLI command -- launch web UI."""

from pathlib import Path

import click

from ..config import load_system_config


@click.command("ui")
@click.option("--port", default=None, type=int, help="Port (default from config)")
@click.option("--host", default=None, help="Host (default from config)")
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on code changes")
def ui(port, host, reload):
    """Launch web UI on localhost (Ctrl+C to stop)."""
    import uvicorn
    from ..db.database import init_db

    init_db()

    config = load_system_config()
    port = port or config["ui"]["port"]
    host = host or config["ui"]["host"]

    click.echo(f"llmflows UI: http://{host}:{port}")
    kwargs = dict(host=host, port=port, log_level="warning")
    if reload:
        import llmflows
        kwargs["reload"] = True
        kwargs["reload_dirs"] = [str(Path(llmflows.__file__).parent)]
    uvicorn.run("llmflows.ui.server:app", **kwargs)
