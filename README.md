<p align="center">
  <h1 align="center">llm-flows</h1>
  <p align="center">Structured workflows for AI coding agents</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/interface-CLI%20%2B%20UI-purple" alt="CLI + UI">
</p>

<p align="center">
  Define multi-step flows with enforced quality gates, run them via CLI or web UI,<br>
  and keep agents disciplined without constant supervision.
</p>

> llm-flows does not replace your coding agent. It gives the agent a workflow to follow: ordered steps, enforced gates, and visible run history. Install it on a personal VM, use it inside Cursor IDE, or add it to a cloud agent platform like Devin, Codex, or GitHub Copilot. Same protocol, same quality gates, everywhere.

<p align="center">
  <img src="assets/flows.png" alt="llm-flows example flow" width="700">
</p>

---

## 🤔 What is llm-flows?

AI coding agents are good at moving fast, but weak at following a reliable process. They skip checks, improvise structure, and often produce inconsistent results. Single-shot prompts work for simple tasks, but fall apart on long, complex workflows — the agent loses track of where it is, skips steps, and drifts from the plan.

`llm-flows` solves this by giving agents a structured protocol they can't skip:

- **Flows** define the ordered steps for a task
- **Gates** enforce quality checks before moving forward
- **Runs** track progress and outcomes
- **CLI or UI** lets humans and agents use the same workflow system

Gates are any shell commands that must exit 0. They range from simple build checks to complex deterministic validations:

- `pytest` — run the test suite
- `npm run lint` — enforce code style
- `grep -q "Success" output.log` — verify a specific string appears in a file
- `find . -name "*.png" | grep -q .` — check that a `.png` file exists

Because gates are just shell commands, you can enforce anything deterministic — file existence, content patterns, data formats, or custom validation scripts. If a gate fails, the agent sees the error output and must fix the issue before advancing.

---

## 🎯 Who this is for

`llm-flows` is for people who use AI coding agents and want them to follow a repeatable delivery process.

**Good fit** if you want to:

- ✅ Enforce build, test, or lint checks between implementation steps
- ✅ Standardize how agents work across projects
- ✅ Run the same workflow in Cursor, local VMs, or cloud agent environments
- ✅ See exactly what step an agent is on and why it is blocked

**Probably not needed** if:

- You only use ad hoc prompts
- You do not want structured multi-step execution
- You are happy relying only on CI after the agent finishes

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

### 3. Start the UI

```bash
llmflows ui
```

This opens the local interface at `http://localhost:4200`. From there, you can start the daemon, create tasks, choose flows, and monitor runs.

### 4. Create a task

Using either the UI or CLI:

```bash
llmflows task create \
  -t "Add login form validation" \
  -d "Add client-side validation, show inline errors, keep styling consistent" \
  --flow default
```

The task is queued and picked up by the background daemon, which launches the agent automatically.

### 5. Watch the progress

Monitor the task in the web UI at `http://localhost:4200`, or follow from the CLI:

```bash
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

### 📖 Core concepts

| Concept | Description |
|---------|-------------|
| **Task** | A unit of work with a title and description |
| **Run** | One execution of a task through a flow |
| **Flow** | A sequence of ordered steps |
| **Step** | A single instruction block the agent must complete |
| **Gate** | A command that must succeed before the run can continue |
| **Daemon** | Background service for managed execution and monitoring |
| **UI** | Local web interface to manage tasks, flows, and runs |
| **Worktree** | Optional isolated Git checkout for safe task execution |

---

## 🧩 Example flow step

A flow step defines what the agent should do and what must pass before advancing:

```json
{
  "name": "validate",
  "content": "# TEST\n\nStart the dev server and verify it compiles without errors.",
  "gates": [
    {
      "command": "npm run build",
      "message": "Build failed. Fix all compilation errors before advancing."
    }
  ]
}
```

What happens:

1. The agent completes the current step
2. `llm-flows` runs the gate command
3. If the command exits successfully, the run advances
4. If it fails, the agent sees the output and must fix the problem first

The workflow is enforced by the tool, not left to agent judgment.

---

## 💡 Why use llm-flows instead of just prompting?

Prompting alone leaves process up to the agent. `llm-flows` adds:

| Without llm-flows | With llm-flows |
|---|---|
| Agent improvises execution order | **Ordered execution** through defined steps |
| Best-effort checks (if any) | **Enforced gates** that block advancement |
| Different approach every time | **Repeatable flows** across runs and projects |
| No visibility until PR review | **Run visibility** with step tracking and logs |
| Tied to one platform | **Agent portability** across local and cloud setups |

Especially useful when the same kind of task happens repeatedly and quality checks matter.

---

## 🚀 Main ways to use it

### 🖥️ Web UI

Use the UI when you want the easiest human-friendly workflow.

```bash
llmflows ui  # http://localhost:4200
```

The web UI lets you:

- 📝 **Create and manage tasks** — create tasks, start runs, pick flows
- 📡 **Live log streaming** — watch the agent work in real time
- 🔧 **Edit flows** — drag-and-drop step reordering, inline content editing, gate configuration
- 📦 **Import/export flows** — share flow definitions as JSON
- 📊 **View the queue** — see pending and executing runs across all projects

The daemon picks up pending tasks, creates a worktree branch, launches the agent, and monitors it. When done, you review the branch and merge.

### ⌨️ CLI-driven local usage

Use the CLI when you want direct control without the UI.

```bash
cd your-project
llmflows register
llmflows task create -t "..." -d "..." --flow default
```

Best for shell-first environments and automation.

### ✏️ Cursor IDE — inline agent execution

Run a task directly from within an agent session. No daemon needed — the agent drives the workflow itself.

```bash
llmflows task create -t "Fix login bug" -d "Safari shows blank page on submit" --start
```

The `--start` flag bootstraps everything inline — registers the project if needed, creates the task and run, sets up a worktree, and outputs the protocol. The agent reads the instructions and works through steps by calling `llmflows mode next`.

**Cursor command** — add `.cursor/commands/llmflows-start.md` to your project so you can trigger flows with `/llmflows-start`:

```markdown
---
description: Initialize llm-flows protocol
---

When starting a task, run:

llmflows task create -t "<title>" -d "<description>" --flow "<flow-name>" --start

If the user doesn't specify a flow name, use "default".

Then follow the protocol instructions in the output.
```

### ☁️ Cloud agent platforms — Devin, Codex, Copilot

Install `llm-flows` on the agent VM and use it in the agent's startup instructions.

```bash
pipx install git+https://github.com/lpakula/llm-flows
llmflows flow import my-flow.json
```

Agent entrypoint example (AGENTS.md, .cursor/rules, or platform-specific config):

```text
When starting a task, run:

llmflows task create -t "<title>" -d "<description>" --flow my-flow --start --no-worktree

Then follow the protocol instructions in the output.
```

Use `--no-worktree` when the platform already provides an isolated checkout.

---

## 🛠️ Flow authoring

Flows are fully customizable. You can define step order, step instructions, gate commands, and project-specific validation logic.

A good flow is usually a small number of clear steps, with fast and reliable gates, instructions specific enough to guide the agent, and strict enough to block bad output without making progress impossible.

### 🎓 Recommended first flow

For new users, start with a simple 3-step workflow:

1. **Understand** — inspect the task and relevant files
2. **Implement** — make the change
3. **Validate** — run tests, build, or lint

This keeps the protocol easy to understand while showing the value of enforced gates.

---

## 🔒 Notes on isolation

`llm-flows` can use Git worktrees for isolated task execution.

- Use **worktrees** when multiple tasks may run in parallel
- Use `--no-worktree` when the environment already gives you isolation
- Use the **UI** when you want local orchestration without manually managing this

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
- **[Development](docs/development.md)** — contributing and local setup

---

## 🤝 Contributing

Contributions, issues, and feedback are welcome.

---

## 📄 License

MIT
