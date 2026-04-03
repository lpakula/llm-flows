<p align="center">
  <h1 align="center">llm-flows</h1>
  <p align="center">Orchestration for background coding agents on your own VM.</p>
  <p align="center">Make one-shot agents more reliable with steps, gates, and model routing.</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/interface-CLI%20%2B%20UI-purple" alt="CLI + UI">
</p>

## What is llm-flows?

`llm-flows` is a local orchestration layer for **background coding agents**.

If you want a cloud-agent style experience for a fraction of the cost, `llm-flows` lets you run repeatable background workflows on your own VM, connect to third-party systems such as GitHub, or use it together with autonomous assistants like [OpenClaw](https://openclaw.ai/).

It works with agent CLIs such as Cursor CLI, Claude Code, or Codex, and can also use local free models through tools such as Ollama or LM Studio. `llm-flows` adds the structure that lets weaker models act as companions to frontier models in the same workflow:

- cheap or local models for routine steps
- stronger cloud models for the hard parts
- gates between steps so the whole workflow stays consistent


Example workflow:

- `research` with a cheap or local model
- `execute` with a frontier model
- `test` with a cheap or local model
- `create-pr` with a cheap model

The goal is to replace one expensive autonomous run with a structured multi-step workflow that uses the right model for each part of the job.


## How it works

`llm-flows` turns one long autonomous run into a deterministic step-by-step workflow.

Each flow is just an ordered list of step instructions. The instruction for each step is plain markdown, and each step can optionally define gates. Flows can be written as JSON and imported directly into `llm-flows`.

Example flow:

```json
{
  "name": "default",
  "steps": [
    {
      "name": "research",
      "position": 0,
      "content": "# RESEARCH\n\nUnderstand the requirements, research the codebase, and create clear tasks to execute."
    },
    {
      "name": "execute",
      "position": 1,
      "content": "# EXECUTE\n\nComplete the tasks from the research step and make the required changes."
    },
    {
      "name": "test",
      "position": 2,
      "content": "# TEST\n\nRun the test suite and fix any failures before moving on.",
      "gates": [
        {
          "command": "pnpm test:e2e",
          "message": "End-to-end tests must pass before advancing."
        }
      ]
    },
    {
      "name": "create-pr",
      "position": 3,
      "content": "# CREATE PR\n\nCommit the finished work, open a pull request, then make sure there are no uncommitted changes left behind.",
      "gates": [
        {
          "command": "test -z \"$(git status --porcelain)\"",
          "message": "Working tree must be clean after the PR step finishes."
        }
      ]
    }
  ]
}
```

Each step runs separately, so you can choose a different model for each part of the workflow.

Artifacts from earlier steps are preserved and passed into later steps.

Between steps, `llm-flows` runs **gates**: deterministic commands that must succeed before the workflow can continue. If a gate fails, that same step is repeated with a clear explanation of what failed and what needs to be fixed.

This is what keeps the workflow reliable: cheaper models can help with some steps, but they cannot silently break the flow and move on.

## Interfaces

`llm-flows` provides two simple interfaces:

- a CLI for creating tasks, starting runs, checking logs, and managing flows - a good interface for autonomous assistants such as OpenClaw
- a local Web UI for monitoring runs and working with flows visually

## Supported agent backends

`llm-flows` works with coding agents that can be launched from the command line.

Built-in backends include:

- [Cursor CLI](https://cursor.com/cli)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- [Codex CLI](https://github.com/openai/codex)
- Qwen Code

## Quick start

### 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/lpakula/llm-flows/main/scripts/install.sh | bash
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/lpakula/llm-flows
```

### 2. Register your project

```bash
cd your-project
llmflows register
```

### 3. Start the daemon

```bash
llmflows daemon start
```

### 4. Create and run a task

```bash
llmflows task create -t "Fix login bug" -d "Safari shows blank page on form submit"
llmflows task start --id <task-id> --flow default
llmflows agent logs <task-id> -f
```

Or use the UI to manage everything through a visual interface:

```bash
llmflows ui
```

## Core ideas

| Concept | Meaning |
|---------|---------|
| **Task** | A unit of work with a title and description |
| **Run** | One execution of a task |
| **Flow** | An ordered sequence of steps |
| **Step** | A single prompt/instruction block |
| **Gate** | A command that must succeed before the next step starts |
| **Daemon** | The background process that orchestrates runs |
| **Alias** | A saved config for agent, model, and flow choices |

## Requirements

- Python 3.11+
- Git
- a Git-based project
- at least one supported agent CLI installed on the VM

> [!WARNING]
> Agent CLIs can read, write, and execute commands on the host. Run them only on infrastructure you trust, ideally an isolated VM.

## Current status

`llm-flows` is still early, but the core idea is stable: orchestrate coding agents on your own machine with steps, gates, and flexible model routing.

## Documentation

- **[CLI Reference](docs/cli.md)** — all commands
- **[Flow Authoring](docs/flows.md)** — writing flows, steps, and gates
- **[Development](docs/development.md)** — contributing and local setup

## Contributing

Contributions, issues, and feedback are welcome.

## License

MIT
