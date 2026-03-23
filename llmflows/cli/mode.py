"""Mode CLI -- step navigation for agents (next/current)."""

import sys

import click

from ..config import get_repo_root, load_system_config
from ..db.database import get_session, init_db
from ..services.context import ContextService
from ..services.flow import FlowService
from ..services.gate import evaluate_gates, evaluate_ifs
from ..services.run import RunService


@click.group("mode")
def mode_cmd():
    """Navigate flow steps. Used by agents during execution."""
    pass


@mode_cmd.command("next")
def mode_next():
    """Advance to the next step and print its content.

    On first call returns the first step of the first flow in the chain.
    When a flow's steps are exhausted, automatically advances to the next
    flow in the chain. After the last flow's last step, returns the
    auto-appended complete step. After complete, prints a finished message.
    """
    repo_root = get_repo_root()
    if repo_root is None:
        click.echo("Not inside a git repository.", err=True)
        raise SystemExit(1)

    context_svc = ContextService.find(repo_root)
    task_id = context_svc.get_current_task_id()
    run_id = context_svc.get_current_run_id()

    if not task_id and not run_id:
        click.echo("No task_id or run_id found in .llmflows/", err=True)
        raise SystemExit(1)

    init_db()
    session = get_session()
    try:
        flow_svc = FlowService(session)
        run_svc = RunService(session)

        # Load the active run directly from DB — single source of truth
        if run_id:
            from ..db.models import TaskRun
            run = session.query(TaskRun).filter_by(id=run_id).first()
        else:
            run = run_svc.get_active(task_id)

        if not run:
            click.echo("No active run found.", err=True)
            raise SystemExit(1)

        flow_name = run.flow_name
        current = run.current_step or ""
        steps = flow_svc.get_flow_steps(flow_name)

        if not steps:
            click.echo(f"Flow '{flow_name}' not found or has no steps.", err=True)
            raise SystemExit(1)

        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        step_vars = {
            "run.id": run.id,
            "task.id": run.task_id,
            "flow.name": flow_name,
        }

        # Gate enforcement: check current step's gates before advancing
        if current and current != "complete":
            step_obj = flow_svc.get_step_obj(flow_name, current)
            if step_obj:
                gates = step_obj.get_gates()
                if gates:
                    failures = evaluate_gates(gates, repo_root, timeout=gate_timeout, variables=step_vars)
                    if failures:
                        lines = ["Gate check failed. Fix these before advancing:\n"]
                        for f in failures:
                            lines.append(f"  ✗ {f['message']}")
                            if f.get("stderr"):
                                for line in f["stderr"].splitlines()[:3]:
                                    lines.append(f"    {line}")
                        lines.append(
                            "\nComplete the requirements, then run "
                            "`llmflows mode next` again.",
                        )
                        sys.stdout.write("\n".join(lines) + "\n")
                        sys.stdout.flush()
                        raise SystemExit(1)

        if not current:
            next_step = steps[0]
        elif current == "complete":
            click.echo("Flow chain completed. No more steps. Stop.")
            return
        elif current in steps:
            nxt = flow_svc.get_next_step(flow_name, current)
            if nxt:
                next_step = nxt
            else:
                # Current flow exhausted — check chain for next flow
                next_flow = run_svc.get_next_flow_in_chain(task_id) if task_id else None
                if next_flow:
                    click.echo(f"\n---\nFlow '{flow_name}' complete. Continuing with '{next_flow}'...\n---\n",
                               err=True)
                    run_svc.advance_to_next_flow(task_id, next_flow)
                    flow_name = next_flow
                    steps = flow_svc.get_flow_steps(next_flow)
                    next_step = steps[0] if steps else "complete"
                else:
                    next_step = "complete"
        else:
            next_step = "complete"

        # IF-condition evaluation: skip steps whose conditions fail
        while next_step and next_step != "complete":
            step_obj = flow_svc.get_step_obj(flow_name, next_step)
            if not step_obj:
                break
            ifs = step_obj.get_ifs()
            if not ifs:
                break
            if evaluate_ifs(ifs, repo_root, timeout=gate_timeout, variables=step_vars):
                break
            # Condition failed — skip this step
            click.echo(f"IF conditions not met for step '{next_step}', skipping.", err=True)
            nxt = flow_svc.get_next_step(flow_name, next_step)
            if nxt:
                next_step = nxt
            else:
                next_flow = run_svc.get_next_flow_in_chain(task_id) if task_id else None
                if next_flow:
                    click.echo(
                        f"\n---\nFlow '{flow_name}' complete. "
                        f"Continuing with '{next_flow}'...\n---\n",
                        err=True,
                    )
                    run_svc.advance_to_next_flow(task_id, next_flow)
                    flow_name = next_flow
                    step_vars["flow.name"] = flow_name
                    steps = flow_svc.get_flow_steps(next_flow)
                    next_step = steps[0] if steps else "complete"
                else:
                    next_step = "complete"

        # Persist next step to DB
        run_svc.update_step(task_id or run.task_id, next_step)

        if next_step == "complete":
            content = context_svc.load_complete_step()
        else:
            content = flow_svc.get_step_content(flow_name, next_step, variables=step_vars)

        if not content:
            click.echo(f"No content found for step '{next_step}'.", err=True)
            raise SystemExit(1)

        click.echo(content)
    finally:
        session.close()


@mode_cmd.command("current")
def mode_current():
    """Re-read the current step without advancing (crash recovery)."""
    repo_root = get_repo_root()
    if repo_root is None:
        click.echo("Not inside a git repository.", err=True)
        raise SystemExit(1)

    context_svc = ContextService.find(repo_root)
    task_id = context_svc.get_current_task_id()
    run_id = context_svc.get_current_run_id()

    if not task_id and not run_id:
        click.echo("No task_id or run_id found in .llmflows/", err=True)
        raise SystemExit(1)

    init_db()
    session = get_session()
    try:
        flow_svc = FlowService(session)
        run_svc = RunService(session)

        if run_id:
            from ..db.models import TaskRun
            run = session.query(TaskRun).filter_by(id=run_id).first()
        else:
            run = run_svc.get_active(task_id)

        if not run:
            click.echo("No active run found.", err=True)
            raise SystemExit(1)

        current = run.current_step or ""
        flow_name = run.flow_name

        if not current:
            click.echo("No current step. Run 'llmflows mode next' to start.", err=True)
            raise SystemExit(1)

        step_vars = {
            "run.id": run.id,
            "task.id": run.task_id,
            "flow.name": flow_name,
        }

        if current == "complete":
            content = context_svc.load_complete_step()
        else:
            content = flow_svc.get_step_content(flow_name, current, variables=step_vars)

        if not content:
            click.echo(f"No content found for step '{current}'.", err=True)
            raise SystemExit(1)

        click.echo(content)
    finally:
        session.close()
