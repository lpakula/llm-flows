"""Agent CLI commands -- list active agents, stream logs."""

import json
import time
from pathlib import Path

import click

from ..db.database import get_session, init_db
from ..services.project import ProjectService
from ..services.run import RunService
from ..services.task import TaskService
from ..services.agent import AgentService
from ..services.worktree import WorktreeService


def _get_session():
    init_db()
    return get_session()


@click.group()
def agent():
    """View active agents and stream logs."""
    pass


@agent.command("list")
@click.option("--all", "-a", "show_all", is_flag=True,
              help="Show agents across all projects")
def agent_list(show_all):
    """List active agents for the current project.

    Use --all to show agents across all projects.
    """
    session = _get_session()
    try:
        project_svc = ProjectService(session)
        task_svc = TaskService(session)

        if show_all:
            projects = project_svc.list_all()
        else:
            current = project_svc.resolve_current()
            if not current:
                click.echo("Not inside a registered project. Use --all to list all agents.")
                raise SystemExit(1)
            projects = [current]

        found = False
        for proj in projects:
            tasks = task_svc.list_by_project(proj.id)
            for t in tasks:
                if AgentService.is_agent_running(proj.path, t.worktree_branch):
                    found = True
                    click.echo(f"  {t.id}  {'running':10s}  {t.name}")
                    click.echo(f"         project: {proj.name}  branch: {t.worktree_branch or '-'}")

        if not found:
            click.echo("No active agents.")
    finally:
        session.close()


def stream_task_logs(task_id: str, follow: bool = True, raw: bool = False) -> None:
    """Resolve log path for a task's active (or latest) run and stream it."""
    session = _get_session()
    try:
        task_svc = TaskService(session)
        run_svc = RunService(session)
        project_svc = ProjectService(session)

        t = task_svc.get(task_id)
        if not t:
            click.echo(f"Task {task_id} not found.")
            raise SystemExit(1)

        run = run_svc.get_active(task_id)
        if not run:
            history = run_svc.get_history(task_id)
            run = history[-1] if history else None

        if not run or not run.log_path:
            click.echo(f"No agent log found for task {task_id}.")
            click.echo("The agent may not have started yet.")
            raise SystemExit(1)

        if run.log_path == "inline":
            click.echo("This run was started inline (--inline). Logs are managed by the calling agent.")
            return

        log_path = Path(run.log_path)

        proj = project_svc.get(t.project_id)
        wt_svc = WorktreeService(proj.path) if proj else None
        wt_path = wt_svc.get_worktree_path(t.worktree_branch) if wt_svc and t.worktree_branch else None
        strip_prefix = str(wt_path) + "/" if wt_path else None
    finally:
        session.close()

    if not log_path.exists():
        click.echo(f"Log file not found: {log_path}")
        raise SystemExit(1)

    tail_log(log_path, follow=follow, raw=raw, strip_prefix=strip_prefix)


def stream_run_logs(run_id: str, follow: bool = True, raw: bool = False) -> None:
    """Stream logs for a specific TaskRun by run_id."""
    session = _get_session()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)

        if not run or not run.log_path:
            click.echo(f"No log found for run {run_id}.")
            raise SystemExit(1)

        if run.log_path == "inline":
            click.echo("This run was started inline (--inline). Logs are managed by the calling agent.")
            return

        log_path = Path(run.log_path)

        task_svc = TaskService(session)
        project_svc = ProjectService(session)
        t = task_svc.get(run.task_id)
        proj = project_svc.get(run.project_id) if t else None
        wt_svc = WorktreeService(proj.path) if proj else None
        wt_path = wt_svc.get_worktree_path(t.worktree_branch) if wt_svc and t and t.worktree_branch else None
        strip_prefix = str(wt_path) + "/" if wt_path else None
    finally:
        session.close()

    if not log_path.exists():
        click.echo(f"Log file not found: {log_path}")
        raise SystemExit(1)

    tail_log(log_path, follow=follow, raw=raw, strip_prefix=strip_prefix)


def tail_log(log_path, follow: bool = True, raw: bool = False,
             strip_prefix: str | None = None) -> None:
    """Tail a log file, optionally following."""
    pos = 0
    idle = 0

    try:
        while True:
            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                if follow:
                    time.sleep(1)
                    continue
                break

            if size > pos:
                idle = 0
                with open(log_path, "r") as f:
                    f.seek(pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        if raw:
                            click.echo(line)
                        else:
                            _print_event(line, strip_prefix=strip_prefix)
                    pos = f.tell()
            elif follow:
                idle += 1
                time.sleep(1)
            else:
                break
    except KeyboardInterrupt:
        pass


@agent.command("logs")
@click.argument("task_id", required=False)
@click.option("--run", "run_id", default=None, help="Stream logs for a specific run ID")
@click.option("--follow", "-f", is_flag=True, help="Follow log output (like tail -f)")
@click.option("--raw", is_flag=True, help="Output raw NDJSON instead of formatted text")
def agent_logs(task_id, run_id, follow, raw):
    """Stream agent logs for a task or specific run.

    Examples:
      llmflows agent logs abc123 -f
      llmflows agent logs --run xyz789 -f
    """
    if run_id:
        stream_run_logs(run_id, follow=follow, raw=raw)
    elif task_id:
        stream_task_logs(task_id, follow=follow, raw=raw)
    else:
        click.echo("Provide a task_id or --run <run_id>.")
        raise SystemExit(1)


def _shorten(path: str, strip_prefix: str | None) -> str:
    """Strip worktree prefix from a path to show project-relative paths."""
    if strip_prefix and path.startswith(strip_prefix):
        return path[len(strip_prefix):]
    return path


def _print_event(line: str, strip_prefix: str | None = None) -> None:
    """Format and print a single NDJSON log event."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        click.echo(line)
        return

    etype = event.get("type", "")

    if etype == "system":
        model = event.get("model", "agent")
        click.secho(f"--- Session started ({model}) ---", fg="bright_black")

    elif etype == "assistant":
        text = ""
        for part in event.get("message", {}).get("content", []):
            if part.get("type") == "thinking":
                continue
            text += part.get("text", "")
        if text.strip():
            click.secho(text.strip(), fg="blue")

    elif etype == "tool_call":
        tc = event.get("tool_call", {})
        if event.get("subtype") == "started":
            desc = _describe_tool_start(tc, strip_prefix)
            click.secho(f"  \u25b6 {desc}", fg="yellow")
        elif event.get("subtype") == "completed":
            desc = _describe_tool_done(tc, strip_prefix)
            lines = desc.split("\n", 1)
            click.secho(f"  \u2714 {lines[0]}", fg="green")
            if len(lines) > 1 and lines[1].strip():
                for output_line in lines[1].splitlines():
                    click.secho(f"    {output_line}", fg="bright_black")

    elif etype == "result":
        duration = (event.get("duration_ms", 0) / 1000)
        click.secho(f"--- Done ({duration:.1f}s) ---", fg="bright_black")

    elif etype == "thinking":
        pass

    else:
        msg = event.get("message") or event.get("error") or event.get("text") or event.get("data")
        if msg:
            text = msg if isinstance(msg, str) else json.dumps(msg)
            click.secho(text, fg="red")


def _extract_tool(tc: dict) -> tuple[str, dict]:
    """Extract (tool_name, call_data) from a tool_call dict."""
    for key in ("readToolCall", "writeToolCall", "editToolCall", "shellToolCall",
                "grepToolCall", "globToolCall", "listToolCall", "deleteToolCall",
                "updateTodosToolCall", "function"):
        if key in tc:
            return key, tc[key]
    for key, val in tc.items():
        if isinstance(val, dict):
            return key, val
    return "unknown", {}


def _describe_tool_start(tc: dict, sp: str | None = None) -> str:
    name, data = _extract_tool(tc)
    args = data.get("args", {})

    if name == "readToolCall":
        return f"Read {_shorten(args.get('path', '?'), sp)}"
    if name == "writeToolCall":
        return f"Write {_shorten(args.get('path', '?'), sp)}"
    if name == "editToolCall":
        return f"Edit {_shorten(args.get('path', '?'), sp)}"
    if name == "shellToolCall":
        cmd = args.get("command", "?")
        return f"Shell: {cmd[:80]}"
    if name == "grepToolCall":
        return f"Grep: {args.get('pattern', '?')}"
    if name == "globToolCall":
        return f"Glob: {args.get('pattern', args.get('glob', '?'))}"
    if name == "listToolCall":
        return f"List {_shorten(args.get('path', '?'), sp)}"
    if name == "deleteToolCall":
        return f"Delete {_shorten(args.get('path', '?'), sp)}"
    if name == "updateTodosToolCall":
        todos = args.get("todos", [])
        return f"Update todos ({len(todos)} items)"
    if name == "function":
        fn_name = data.get("name", "tool")
        try:
            fn_args = json.loads(data.get("arguments", "{}"))
            if fn_args.get("command"):
                return f"{fn_name}: {fn_args['command'][:80]}"
            if fn_args.get("path"):
                return f"{fn_name}: {_shorten(fn_args['path'], sp)}"
            if fn_args.get("pattern"):
                return f"{fn_name}: {fn_args['pattern']}"
        except (json.JSONDecodeError, AttributeError):
            pass
        return fn_name

    label = name.replace("ToolCall", "").replace("_", " ").capitalize()
    detail = args.get("path", args.get("pattern", args.get("command", "")))
    if detail:
        return f"{label}: {_shorten(str(detail), sp)[:80]}"
    return label


def _describe_tool_done(tc: dict, sp: str | None = None) -> str:
    name, data = _extract_tool(tc)
    result = data.get("result", {})
    success = result.get("success", {})
    args = data.get("args", {})

    if name == "readToolCall" and success:
        path = _shorten(args.get("path", "?"), sp)
        return f"Read {path} ({success.get('totalLines', '?')} lines)"
    if name == "writeToolCall" and success:
        path = _shorten(success.get("path", args.get("path", "?")), sp)
        return f"Wrote {path} ({success.get('linesCreated', '?')} lines)"
    if name == "editToolCall" and success:
        return f"Edited {_shorten(args.get('path', '?'), sp)}"
    if name == "shellToolCall":
        exit_code = success.get("exitCode", success.get("exit_code"))
        stdout = success.get("stdout") or success.get("output") or ""
        parts = []
        if exit_code is not None:
            parts.append(f"Shell completed (exit {exit_code})")
        else:
            parts.append("Shell completed")
        if stdout.strip():
            parts.append("\n" + stdout.strip())
        return "\n".join(parts)
    if name == "grepToolCall":
        return "Grep completed"
    if name == "globToolCall":
        return "Glob completed"
    if name == "updateTodosToolCall":
        return "Todos updated"
    if name == "function":
        return f"{data.get('name', 'tool')} completed"

    label = name.replace("ToolCall", "").replace("_", " ").capitalize()
    return f"{label} completed"
