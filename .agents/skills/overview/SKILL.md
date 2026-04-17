---
name: llmflows-overview
description: Explain what llm-flows is, its architecture, and key concepts. Use when the user asks what llm-flows is, how it works, what it can do, or needs an overview of the platform.
---

# llm-flows Overview

llm-flows is a local workflow orchestrator for AI agents — think "CI for coding agents." It splits autonomous work into ordered steps with gates (commands that must pass), so jobs don't advance on bad output. Everything runs on your machine; nothing is sent to third-party services beyond the LLM API calls you configure.

---

## Core Architecture

```
┌─────────┐     ┌────────┐     ┌──────────┐
│   CLI   │────▶│  Daemon │────▶│ Executors │──▶ Pi / Code Agent / Shell
│  / UI   │     │ (engine)│     └──────────┘
└─────────┘     └────────┘
                     │
                ┌────┴────┐
                │   DB    │  (SQLite, ~/.llmflows/)
                └─────────┘
```

- **CLI** (`llmflows`) — terminal interface for all operations: register spaces, manage flows, start runs, control the daemon
- **UI** — web dashboard (FastAPI + React) for the same operations with a visual interface
- **Daemon** — background engine that polls for queued runs, executes steps, evaluates gates, and advances flows
- **Executors** — per-step-type backends that launch the right agent or command
- **DB** — local SQLite database storing spaces, flows, runs, settings, and agent config

---

## Key Concepts

### Spaces

A space is a registered project directory. It is the top-level organizational unit — all flows and runs belong to a space. Spaces have:

- A name and filesystem path (your repo or project folder)
- Space variables — key-value pairs available as `{{space.KEY}}` in step content and as environment variables in shell steps
- Concurrency limits — how many runs can execute simultaneously
- Their own flows, runs, and settings

Register a space with `llmflows register` or through the UI.

### Flows

A flow is an ordered list of steps that execute sequentially. Each step runs as a separate agent process, produces artifacts (files), and those artifacts automatically become context for subsequent steps. Flows have:

- A name and description
- An ordered list of steps
- Optional requirements (tools and variables the flow needs)

Flows are the automation definitions — they describe *what* to do. Runs are the executions.

### Runs

A run is a single execution of a flow. When you start a run, the daemon picks it up and processes steps one by one. Runs track:

- Status: queued → running → completed (or paused / interrupted)
- Current step position
- Cost and token usage across all steps
- Artifacts and logs from each step
- Outcome (success/failure)

You can pause, resume, stop, and retry runs.

### Steps

Each step is a unit of work with a markdown prompt, a step type, and optional gates/IFs. Step types control *how* the step executes:

- **agent** — runs via Pi (built-in AI agent with tools). Use for most steps: research, analysis, content generation, automation
- **code** — runs via an external coding agent (Cursor, Claude Code). Only for source-code editing tasks
- **shell** — runs a shell command directly, no AI involved. For deterministic tasks: builds, deploys, scripts
- **hitl** — human-in-the-loop. Like default, but pauses for user input before the flow continues

### Artifacts

Every step writes output to an artifacts directory. The primary output is `_result.md`. The daemon automatically collects artifacts from completed steps and passes them as context to subsequent steps — this is how steps communicate.

### Gates

Shell commands attached to a step that must exit 0 before the flow advances. If a gate fails, the agent is relaunched with failure details to fix the problem. Gates are how you enforce quality — tests must pass, files must exist, builds must succeed.

### IFs (Conditional Steps)

Shell commands evaluated *before* a step runs. If any IF fails, the step is skipped entirely. Use for conditional logic — only lint Python if `pyproject.toml` exists, only deploy if on the main branch.

### The Daemon

The daemon is the background engine. It:

1. Polls for queued runs across all spaces
2. Launches steps using the appropriate executor
3. Waits for async agents to finish
4. Evaluates gates and retries on failure
5. Advances to the next step or completes the run

Start it with `llmflows daemon start` or from the UI. Without the daemon running, queued runs won't execute.

### Agent Aliases

Agent aliases are pre-defined tiers (`mini`, `normal`, `max`) that map to an agent backend + model. Each tier exists per type:

- **pi** — used for `agent` and `hitl` steps (the built-in Pi agent)
- **code** — used for `code` steps (external coding agents like Cursor, Claude Code)

Aliases are configured in the UI (Settings > Agents) or via `llmflows agent alias update`.

### Inbox

The inbox is the human-in-the-loop queue. It shows:

- **Awaiting items** — hitl steps paused for your input (you read the agent's output and respond)
- **Completed runs** — finished flows with summaries and optional attachments

This is where automation meets human judgment.

### Tools

Tools extend what agents can do during runs. Currently available:

- **Web Search** — gives Pi agents `web_search` and `web_fetch` capabilities. Supports DuckDuckGo (free) and Brave (API key required)

Enable tools in Settings > Tools.

---

## Getting Started

1. **Register a space**: `llmflows register` in your project directory
2. **Start the daemon**: `llmflows daemon start`
3. **Configure agents**: Set up API keys and agent aliases in the UI (Settings > Agents)
4. **Enable tools**: In Settings > Tools, turn on web search and any other tools your flows will need
5. **Add skills** (optional): In the space's Skills tab, add prompt snippets that give agents domain knowledge for your project
6. **Create a flow**: Define steps in the UI flow editor, via CLI (`llmflows flow`), or ask the Chat assistant to build one
7. **Run a flow**: Click "Run" in the UI or use `llmflows run schedule --flow <flow-id>`
8. **Monitor**: Watch progress in the UI, check the inbox for hitl items

Optional: set up the **Gateway** (Settings > Gateway) to control llm-flows remotely — receive notifications and approve hitl steps from your phone or messaging app.

---

## UI Navigation

- **Dashboard** — overview of spaces and recent activity
- **Inbox** — human-in-the-loop items and completed run notifications
- **Chat** — AI assistant that can explain concepts and create flows for you
- **Space** — per-space view with flows, runs, skills, and settings
- **Flow Editor** — visual editor for flow steps, gates, and conditions
- **Settings** — daemon config, agent aliases, API keys, tools, gateway
