# llm-flows — Agent Guide

## Project overview

**llm-flows** (`llmflows`) is a Python 3.11+ workflow orchestrator for autonomous coding agents. It has:
- A CLI (`llmflows`) built with Click
- A daemon that polls and executes flow runs
- A FastAPI backend + React/Vite frontend
- A central SQLite DB at `~/.llmflows/llmflows.db`
- Per-space run artifacts under `.llmflows/<flow-name>/runs/` inside each registered project directory

## Key directories

```
llmflows/
  cli/          Click command groups (daemon, flow, run, agent, space, ui, connectors)
  db/           SQLAlchemy models, Alembic migrations (SQLite, batch_alter_table pattern)
  services/     Core logic — daemon.py, flow.py, run.py, agent.py, context.py, gate.py
    executors/  PiExecutor (agent/hitl steps) and CodeExecutor (code steps)
  ui/
    server.py   FastAPI app (REST + WebSocket)
    frontend/   Vite + React 19 + Tailwind 4 + TypeScript source
    static/     Production build output (committed, served by FastAPI)
  utils/        git.py (diff helpers, get_worktree_diff), other utilities
  defaults/     Bundled prompt templates and default config
  tools/        Built-in MCP servers (TypeScript)
tests/          Pytest suite — test_api.py, test_services.py, test_models.py, test_context.py
scripts/
  test.sh       Preferred test runner (Docker-based)
  build.py      Hatch build hook (compiles frontend if static/index.html missing)
flows/          Example/exported flow JSON files
.agents/skills/ Agent skills injected at step runtime (cli/SKILL.md, release/SKILL.md, testing/SKILL.md)
```

## Testing

See `.agents/skills/testing/SKILL.md` for the full testing guide (unit tests, daemon tick simulation, Playwright browser testing, worktree isolation).

Quick reference:
```bash
./scripts/test.sh        # full suite via Docker (matches CI)
pytest                   # direct, needs pip install -e ".[dev]"
llmflows daemon tick     # one-shot daemon tick, no background process
```

## Git worktrees

- `.worktrees/` is in `.gitignore` — always create worktrees there:
  ```bash
  git worktree add .worktrees/<name> -b <name>
  ```
- Worktrees are a workflow convention, not enforced by the engine.
- `llmflows/utils/git.py` has `get_worktree_diff(base, cwd)` for generating LLM-friendly diffs.
- Each worktree needs its own venv: `python -m venv .venv && .venv/bin/pip install -e '.[dev]' -q`
- Set `LLMFLOWS_HOME=~/.llmflows-worktree-<name>` for a fully isolated DB, daemon, and config.

## Key patterns and abstractions

**Step types**: `"agent"` / `"hitl"` → `PiExecutor`; `"code"` → `CodeExecutor` (external CLI agent subprocess). Unknown types normalise to `"agent"`.

**Step directory naming** (used by `ContextService.step_dir_name`):
```
{position:02d}-{step-name-lowercased-with-spaces-replaced-by-hyphens}
```
e.g. step `"Research and Implement"` at position 1 → `01-research-and-implement`

**Run artifact layout**:
```
.llmflows/<flow-name>/runs/<run_id>/artifacts/
  00-step-name/
    _result.md      required — passed as context to next steps
    hitl.md         hitl steps only — user-facing question
  inbox.md          optional — triggers Telegram/Slack notification on run completion
~/.llmflows/attachments/<run_id>/
  screenshot.png    images rendered inline in notifications
```

**Template variables** available in step content and gates:
`{{run.id}}`, `{{run.dir}}`, `{{step.dir}}`, `{{attachment.dir}}`, `{{flow.dir}}`, `{{flow.name}}`, `{{flow.<VAR>}}`, `{{space.<VAR>}}`, `{{hitl.response.N}}`

**DB models**: `Flow` → `FlowStep[]` (ordered by `position`). `FlowRun` → `StepRun[]`. `FlowRun.flow_snapshot` stores a JSON snapshot of the flow at run time (variables baked in).

**Flow JSON import/export**: `llmflows flow import flows/my-flow.json` / `llmflows flow export --output flows.json`

## Frontend development

```bash
# Dev mode (Vite HMR + FastAPI auto-reload)
llmflows ui --dev

# Production build (output committed to llmflows/ui/static/)
cd llmflows/ui/frontend && npm run build
```

Stack: React 19, React Router 7, Vite 6, Tailwind 4, TypeScript 5.7, lucide-react.

The production static build is committed so users installing via pip don't need Node.js.

## Database migrations

Alembic under `llmflows/db/migrations/versions/`. Always use `batch_alter_table` for column changes (SQLite compatibility):
```python
with op.batch_alter_table("table_name") as batch_op:
    batch_op.add_column(sa.Column(...))
```

## Dependencies

- Python ≥ 3.11
- Runtime: `click`, `sqlalchemy`, `alembic`, `fastapi`, `uvicorn`, `litellm`, `jinja2`, `rich`, `croniter`, `python-telegram-bot`, `slack-bolt`
- Dev: `pytest`, `pytest-cov`, `httpx`
- Package manager: `uv` (`uv lock` to regenerate lockfile after dep changes)

## Conventions

- **Do not push to remote** unless explicitly asked.
- **Do not modify files outside the target worktree** during feature development.
- Skills live in `.agents/skills/<name>/SKILL.md` and are injected into agent prompts at runtime by step configuration.
- The `release` skill documents the full release process (build frontend → bump version → commit → tag → push).
