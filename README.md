<p align="center">
  <h1 align="center">llm-flows</h1>
  <p align="center">CI for coding agents.</p>
  <p align="center">Turn one long autonomous coding run into a reliable step-by-step workflow.</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/interface-CLI%20%2B%20UI-purple" alt="CLI + UI">
</p>

## What is llm-flows?

`llm-flows` is a local workflow runner for **background coding agents**.

Instead of asking an agent to do everything in one long run, `llm-flows` breaks the job into explicit stages such as:

- `research`
- `execute`
- `test`
- `create-pr`

Between stages, it runs checks called **gates**. The workflow only moves forward after each gate passes.

This makes coding agents:

- more reliable
- cheaper to run
- easier to inspect
- safer to automate

It brings a cloud-agent style workflow to your own VM, so you can run repeatable coding jobs locally with more control and lower cost.

`llm-flows` works with agent CLIs such as Cursor CLI, Claude Code, Codex, and Qwen Code.

You can:

- integrate with systems such as GitHub for orchestration and feedback
- use it together with autonomous assistants like [OpenClaw](https://openclaw.ai/)
- route some steps to local models through tools such as Ollama or LM Studio

## Why use it?

One-shot autonomous runs are convenient, but they are hard to trust. When they fail, they often fail late: after making the wrong changes, skipping tests, or drifting away from the original task.

`llm-flows` adds structure around the agent run:

- each step runs separately
- each step can use a different model
- artifacts from earlier steps carry into later ones
- gates block bad output before the workflow advances

This lets cheap or local models handle routine work while stronger models handle the hard parts.

## Example workflow

A typical flow might look like this:

- `research` with a cheap or local model
- `execute` with a frontier model
- `test` with a cheap or local model
- `create-pr` with a cheap model

The goal is to replace one expensive autonomous run with a structured workflow that uses the right model for each part of the job.


## How it works

`llm-flows` turns one long autonomous coding run into a step-by-step workflow.

A flow is an ordered list of steps:

- each step contains a markdown instruction block
- each step runs separately
- each step can use a different model
- each step can define gates

Artifacts from earlier steps are preserved and passed into later steps.

Between steps, `llm-flows` runs **gates**: commands that must succeed before the workflow can continue. If a gate fails, the same step is repeated with a clear explanation of what failed and what needs to be fixed.

This is what keeps the workflow reliable: cheaper models can help with some steps, but they cannot silently break the flow and move on.

Flows can be written as JSON and imported directly into `llm-flows`.

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

## Interfaces

`llm-flows` provides two simple interfaces:

- a CLI for creating tasks, starting runs, checking logs, and managing flows
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

### 2. Register your space

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

## Key terms

- **Task** - a unit of work with a title and description
- **Run** - one execution of a task
- **Flow** - an ordered sequence of steps
- **Gate** - a command that must pass before the workflow can continue

## Requirements

- Python 3.11+
- Git
- a working directory for your flows
- at least one supported agent CLI installed on the VM

> [!WARNING]
> Agent CLIs can read, write, and execute commands on the host. Run them only on infrastructure you trust, ideally an isolated VM.

## Current status

`llm-flows` is still early, but the core idea is stable: make coding agents more reliable with step-by-step workflows, gates, and flexible model routing.

## Documentation

- **[CLI Reference](docs/cli.md)** — all commands
- **[Flow Authoring](docs/flows.md)** — writing flows, steps, and gates
- **[Development](docs/development.md)** — contributing and local setup

## Contributing

Contributions, issues, and feedback are welcome.

## License

MIT
