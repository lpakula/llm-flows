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
.agents/skills/ Agent skills injected at step runtime (cli/SKILL.md, release/SKILL.md)
```

## Running tests

**Preferred** — Docker-based, matches CI:
```bash
./scripts/test.sh                              # full suite
./scripts/test.sh tests/test_api.py            # single file
./scripts/test.sh tests/test_services.py::TestFoo::test_bar  # single test
./scripts/test.sh --rebuild                    # rebuild image after dep changes
```

**Direct pytest** (no Docker, needs `pip install -e ".[dev]"`):
```bash
pytest
pytest tests/test_api.py -v
```

Coverage is reported automatically (`--cov=llmflows --cov-report=term-missing`).

## Git worktrees

- `.worktrees/` is in `.gitignore` — always create worktrees there:
  ```bash
  git worktree add .worktrees/<name> -b <name>
  ```
- Worktrees are a workflow convention, not enforced by the engine.
- `llmflows/utils/git.py` has `get_worktree_diff(base, cwd)` for generating LLM-friendly diffs.

## Testing from a worktree

Each worktree must have its own isolated Python environment. **Never** install into the system Python or the main repo's venv when working in a worktree.

```bash
cd .worktrees/<name>

# Create venv (once)
python -m venv .venv

# Install project + dev deps
.venv/bin/pip install -e '.[dev]' -q

# Run tests (always from inside the worktree)
.venv/bin/pytest
```

## Running the UI from a worktree (fully isolated)

Set `LLMFLOWS_HOME` to redirect every path (DB, config, PID file, daemon log) to a private directory. This gives the worktree instance its own daemon and DB — it cannot read, write, or disturb production runs.

```bash
cd .worktrees/<name>

export LLMFLOWS_HOME=~/.llmflows-worktree-<name>

# Register the worktree as a space in the isolated DB (safe to re-run)
.venv/bin/llmflows register --name worktree-<name>

# Start UI + daemon on a separate port
.venv/bin/llmflows ui --port 8899
```

**What `LLMFLOWS_HOME` isolates:**
- `$LLMFLOWS_HOME/llmflows.db` — separate DB, no production data
- `$LLMFLOWS_HOME/daemon.pid` — separate PID file, separate daemon process
- `$LLMFLOWS_HOME/daemon.log` — separate log
- `$LLMFLOWS_HOME/config.toml` — separate config

The production daemon and UI continue running unaffected on their default port.

**Teardown** — stop the worktree daemon when done:
```bash
LLMFLOWS_HOME=~/.llmflows-worktree-<name> .venv/bin/llmflows daemon stop
```

## Taking UI screenshots from a worktree

Use Playwright from the worktree venv:

```bash
.venv/bin/pip install playwright -q
.venv/bin/playwright install chromium --with-deps -q
.venv/bin/python -m playwright screenshot http://localhost:8899 screenshot.png --wait-until networkidle
```

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
