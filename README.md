<p align="center">
  <h1 align="center">llm-flows</h1>
  <p align="center">Reliable orchestration for autonomous background coding agents</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/interface-CLI%20%2B%20UI-purple" alt="CLI + UI">
</p>

<p align="center">
  Define multi-step flows with enforced quality gates and keep agents disciplined without constant supervision.
</p>

Autonomous background agents are a great idea — until the task gets complex. Agents drift, skip steps, and hallucinate in ways that are hard to catch and expensive to fix. `llm-flows` brings structure to the chaos: explicit steps, deterministic quality gates, and a protocol the agent must follow — not just try to follow.

It is designed for **autonomous background runs** (a VM/runner that can clone repos, start services, run tests, commit and open PRs).

🖥️ Supported on self-hosted VMs with local agent CLIs:
- Cursor CLI: `agent -p -f "<prompt-file>"`
- Claude Code: `claude -p "<prompt>"`
- Codex CLI: `codex exec "<prompt>"`

> [!NOTE]
> At least one of the above agent CLIs must be installed on the VM before running `llm-flows`.

> [!WARNING]
> Local agent CLIs run in **full permission mode** — they can read, write, and execute anything on the host. Always run them on an **isolated VM**; never unsupervised on your local machine.

☁️ Supported on cloud agent VMs:

Any cloud agent automation is supported as long as you can install `llm-flows` and provide an initial prompt. Integration works via inline mode (`--inline --no-worktree`), where the agent bootstraps and drives the flow itself — no daemon or trigger integration required (triggering is handled by the cloud agent platform) (e.g. **[Cursor Automations](docs/cloud-agents.md)**, **[GitHub Copilot](docs/cloud-agents.md)**).

🔗 Supported trigger integrations:
- Local UI — create and trigger runs from the local web UI
- GitHub issues — trigger runs via `@llmflows` comments on any issue
- Jira tickets — *(coming soon)*



## 🤔 What is llm-flows?

Autonomous background agents work great as a **single-shot prompt** (for example: "read the GitHub issue, implement, and open a PR").

But once your environment becomes real — multiple microservices, multiple repos, dev servers, health checks, integration tests, log inspection, UI verification — agents drift. They skip steps, improvise structure, and often fail in ways that are expensive to discover late.


💡 What if your background agent could:

- Clone multiple services from GitHub
- Start multiple services (e.g. frontend, backend) and wait for them to be healthy
- Implement a feature with changes spanning multiple services
- Run full integration tests — API calls, server log verification, UI screenshots
- Commit and open PRs for each service to deliver a single feature

All in one go, reliably, without fear of the agent drifting halfway through a complex workflow.


💡 What if you could choose the model and control the flow for every run — and save money doing it? e.g. trigger a run with a simple GitHub comment:

```
Fix the login timeout on mobile

@llmflows --agent cursor --model gemini-3-flash --flow bug-fix
```

Or with a predefined alias:

```
@llmflows --alias simple
```

Use a cheap, fast model for routine fixes. Switch to a more powerful one only when the task demands it — without changing any config.

You can even split the work across runs for a single task: use an expensive model for a run that analyses the codebase and produces a detailed implementation plan, then trigger a second run with a cheaper model to execute the plan. Same task, different agents, full context from the previous run.

`llm-flows` gives agents a structured protocol they must follow:

- **Flows** — ordered steps the agent executes one by one
- **Gates** — shell commands that must pass before the agent can advance (build, tests, health checks, log assertions, screenshots — anything deterministic)
- **Runs** — full execution history with step tracking and logs

## 🎯 Who this is for

`llm-flows` is for teams running autonomous agents on complex, multi-service environments where a single-shot prompt isn't enough to deliver a feature end-to-end — and agent drift is expensive.

**Good fit** if you need to:

- ✅ Coordinate work across multiple repos or services in a single automated run
- ✅ Enforce deterministic checks (build, tests, health, logs, screenshots) at each step
- ✅ Run the same reliable workflow across projects and environments
- ✅ Control which agent and model runs each workflow — without being locked into one provider or tier

**Probably not for you** if:

- Your tasks are simple single-repo and a one-shot prompt gets the job done
- You're happy with existing cloud coding agents as-is

---

## ⚡ Quick start

The fastest way to try `llm-flows` is in an existing Git project.

### 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/lpakula/llm-flows/main/scripts/install.sh | bash
```

Or install directly:

```bash
pipx install git+https://github.com/lpakula/llm-flows
```

### 2. Register your project

```bash
cd your-project
llmflows register
```

### 3. Start the daemon and UI

```bash
llmflows daemon start
llmflows ui
```

This starts the background daemon and opens the local interface at `http://localhost:4200`. From there, you can create tasks, choose flows, and monitor runs.

### 4. CLI (Optional)

If you prefer the terminal, you can also manage tasks via the CLI:

```bash
llmflows task create --title "..." --description "..."
llmflows task start --id <task-id> --flow default
llmflows run logs <run-id> --follow
```

---

## ⚙️ How it works

`llm-flows` follows a simple lifecycle:

```
📋 Create task  →  🚀 Start run  →  🔁 Step loop  →  ✅ Complete
```

📋 **Create** — a task with a title and description\
🚀 **Start** — bootstraps the run, outputs the protocol\
🔁 **Step loop** — agent calls `llmflows mode next` to get each step; gates are checked before advancing\
✅ **Complete** — agent summarizes the work with `llmflows run complete`

Gates are shell commands that must exit 0. If `npm run build` fails, the agent sees the error output and must fix the code. No skipping.

### 🌿 Parallel task execution

On a self-hosted VM, each task runs in its own **Git worktree** — an isolated checkout on a dedicated branch. This means multiple tasks can run in parallel without interfering with each other. Each agent works in its own branch, commits its changes there, and opens a PR when done. The main repo stays untouched until you review and merge.

### 🧠 Persistent memory 

When running on a self-hosted VM, every completed run is stored locally — including the full execution summary. When you post a follow-up comment on a GitHub issue, the agent receives the context of all previous runs on that task. You can iterate on a feature across multiple runs without re-explaining the history — the agent already knows what was done, how and why.

This makes fully autonomous iteration possible: comment, let the agent run, review the PR, comment again — all without manual context handoff.

### 📖 Core concepts

| Concept | Description |
|---------|-------------|
| **Task** | A unit of work with a title and description |
| **Run** | One execution of a task through a flow |
| **Flow** | A sequence of ordered steps |
| **Step** | A single instruction block the agent must complete |
| **Gate** | A command that must succeed before the run can continue |
| **Daemon** | Background service for managed execution and monitoring |

---

## 💡 Why use llm-flows instead of single-shot runs?

Single-shot runs give the agent everything at once and hope for the best. `llm-flows` injects step-specific context at the right moment — so the agent stays focused, follows the defined order, and doesn't drift across a long, complex workflow. Especially useful when tasks require multiple steps to happen in a specific order — setting up environments, running builds, passing checks — before the work is considered done.

| Without llm-flows | With llm-flows |
|---|---|
| Agent improvises execution order | **Ordered steps** through defined flows |
| Best-effort checks (if any) | **Enforced gates** that block advancement on failure |
| Different approach every time | **Repeatable flows** across runs and projects |
| No visibility until PR review | **Step tracking** with logs and run history |
| Locked into one hosted tier | **Model flexibility** — pick backend and model per run |


---

## 📋 Requirements

- Python 3.11+
- Git
- A Git-based project
- A coding agent or human operator able to run shell commands

---

## 📈 Current status

`llm-flows` is in an early stage, intended for users who want to experiment with structured agent workflows. The core ideas are stable, while some commands and UX may still evolve.

---

## 📚 Documentation

- **[CLI Reference](docs/cli.md)** — all commands
- **[Flow Authoring](docs/flows.md)** — writing flows, steps, and gates
- **[Cursor IDE](docs/cursor-ide.md)** — inline usage from within Cursor
- **[Cloud Agents](docs/cloud-agents.md)** — Cursor Automations, GitHub Copilot, and other cloud agent integrations
- **[Development](docs/development.md)** — contributing and local setup

---

## 🤝 Contributing

Contributions, issues, and feedback are welcome.

---

## 📄 License

MIT
