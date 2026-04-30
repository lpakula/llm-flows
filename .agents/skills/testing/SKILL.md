---
name: testing
description: Testing guide for the llm-flows project. Use when writing or running tests, simulating daemon behaviour, doing browser/UI testing with Playwright, testing from a git worktree, or debugging a run transition. Covers unit tests, daemon tick simulation, and correct Playwright screenshot patterns.
---

# llmflows Testing Guide

## Unit tests

**Preferred — Docker (matches CI):**
```bash
./scripts/test.sh                                              # full suite
./scripts/test.sh tests/test_api.py                            # single file
./scripts/test.sh tests/test_services.py::TestFoo::test_bar    # single test
./scripts/test.sh --rebuild                                    # after dep changes
```

**Direct pytest** (faster, no Docker, needs `pip install -e ".[dev]"`):
```bash
pytest
pytest tests/test_api.py -v
pytest tests/test_services.py::TestFoo::test_bar -v
```

Coverage is reported automatically (`--cov=llmflows --cov-report=term-missing`).

### Test database

Tests use an **in-memory SQLite DB** via the `test_db` fixture in `conftest.py` — no setup needed. Never use the real `~/.llmflows/llmflows.db` in tests.

### Writing new tests

- Mirror the file being tested: `llmflows/services/foo.py` → `tests/test_foo.py`
- Use the existing `test_db` and `client` fixtures (see `conftest.py`)
- All service classes accept a SQLAlchemy `Session` — inject `test_db`

---

## Simulating a daemon tick

Use `llmflows daemon tick` to process all pending run transitions once, synchronously, with no background process and no PID file. Safe to call inside a worktree or test without conflicting with a running daemon.

**CLI:**
```bash
llmflows daemon tick             # one tick, quiet
llmflows daemon tick --verbose   # with logs mirrored to stdout
```

**From a worktree** (prepend `.venv/bin` so the worktree binary is used):
```bash
export LLMFLOWS_HOME=~/.llmflows-worktree-<name>
export PATH="$(pwd)/.venv/bin:$PATH"
llmflows daemon tick --verbose
```

**From Python** (e.g. an integration test):
```python
from llmflows.db.database import init_db
from llmflows.services.daemon import Daemon

init_db()
Daemon()._tick()
```

`Daemon.__init__` is lightweight (no threads, no sockets). Call `_tick()` as many times as needed to advance a multi-step run.

---

## Testing steps that require agent execution

The daemon calls `AgentService.prepare_and_launch_step` to launch a real agent subprocess. In tests, patch that method out and write the expected artifacts directly, then tick again to let the daemon advance.

**Pattern 1 — mock the agent launch:**

```python
from unittest.mock import patch
from pathlib import Path
from llmflows.db.database import init_db, get_session
from llmflows.services.daemon import Daemon
from llmflows.services.run import RunService

init_db()
session = get_session()
# ... set up space, flow, enqueue run ...

def fake_agent(self, run_id, step_name, step_position, **kwargs):
    step_dir = Path(f"/tmp/test-space/.llmflows/my-flow/runs/{run_id}/artifacts"
                    f"/{step_position:02d}-{step_name.lower().replace(' ', '-')}")
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "_result.md").write_text("done")
    return True, "", ""

with patch("llmflows.services.agent.AgentService.prepare_and_launch_step", fake_agent):
    Daemon()._tick()  # starts step → fake writes artifact → step marked complete
    Daemon()._tick()  # evaluates gates → advances to next step or finalises run
```

**Pattern 2 — manually complete a step then tick:**

Useful when you only care about run-level transitions, not step content.

```python
# First tick starts the step
Daemon()._tick()

# Write the artifact and mark the step done manually
run_svc = RunService(session)
step_run = run_svc.get_active_step(run.id)
step_dir = Path(f".../{step_run.step_position:02d}-{step_run.step_name.lower().replace(' ', '-')}")
step_dir.mkdir(parents=True, exist_ok=True)
(step_dir / "_result.md").write_text("done")
run_svc.mark_step_completed(step_run.id, outcome="completed")
session.commit()

# Tick to evaluate gates and advance
Daemon()._tick()
```

Gates are shell commands evaluated by the daemon between steps. If a gate checks for a file, write that file before the second tick.

---

## Browser / UI testing with Playwright

### Setup

Install Playwright into the worktree venv:
```bash
.venv/bin/pip install playwright -q
.venv/bin/playwright install chromium --with-deps -q
```

### Starting the isolated UI

Use `--no-daemon` to skip daemon auto-spawning — required when taking screenshots or running UI tests where you don't need run processing:

```bash
export LLMFLOWS_HOME=~/.llmflows-worktree-<name>
export PATH="$(pwd)/.venv/bin:$PATH"

llmflows register --name worktree-<name>   # idempotent
llmflows ui --port 4500 --no-daemon &
sleep 5
```

The FastAPI backend runs on `PORT+1` (e.g. `4501` when UI is on `4500`).

### Populating the worktree DB with test data

If the feature requires real data in the UI (e.g. a flow detail page, a run view), create a minimal fixture flow and import it:

```bash
export LLMFLOWS_HOME=~/.llmflows-worktree-<name>
export PATH="$(pwd)/.venv/bin:$PATH"

llmflows register --name worktree-<name>
llmflows flow import flows/my-fixture-flow.json
```

A minimal fixture flow only needs a name and one or two steps — tailor it to make the specific feature visible. Skip this step entirely if the feature is visible without any flow data.

### Taking screenshots

**Do not screenshot the root URL.** `http://localhost:4500` renders an empty chat view with no space or flow visible.

Instead:
1. Use the API (`http://localhost:4501`) to create the minimum test data that makes the feature visible.
2. Navigate Playwright to the specific path where the feature is rendered.
3. Screenshot that path.

```python
import requests
from playwright.sync_api import sync_playwright

api = "http://localhost:4501"

# testing-flow.json was already imported — fetch what's there
space = requests.get(f"{api}/api/spaces").json()[0]
flows = requests.get(f"{api}/api/spaces/{space['id']}/flows").json()
flow = next(f for f in flows if f["name"] == "testing-flow")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(f"http://localhost:4500/spaces/{space['id']}/flows/{flow['id']}")
    page.wait_for_load_state("networkidle")
    page.screenshot(path="/path/to/attachment.png")
    browser.close()
```

### Teardown

```bash
lsof -ti tcp:4500 2>/dev/null | xargs kill -15 2>/dev/null || true
```

---

## Testing from a worktree

```bash
cd .worktrees/<name>
python -m venv .venv              # once
.venv/bin/pip install -e '.[dev]' -q
.venv/bin/pytest                  # always run from inside the worktree
```

Never run tests from the main repo root when testing worktree changes — it tests the main branch code, not your changes.
