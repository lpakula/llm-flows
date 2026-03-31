---
name: llmflows-cli
description: Use the llmflows CLI to manage projects, tasks, runs, flows, aliases, and the daemon. Use when the user wants to register a project, create or start tasks, manage flows and steps, configure aliases, check run status, or perform any llmflows operation from the terminal.
---

# llmflows CLI

llmflows is a workflow orchestrator for autonomous coding agents. All operations available in the web UI can be performed via CLI.

## Prerequisites

- llmflows must be installed (`llmflows --version` to verify)
- For most commands, run from inside a registered project directory
- Register first if needed: `llmflows register`

## Project Setup

```bash
# Register current directory as a project
llmflows register
llmflows register --name "My App"

# List all registered projects
llmflows project list

# Rename a project
llmflows project update --name "New Name"

# View/update settings
llmflows project settings
llmflows project settings --git-repo false
```

## Task Lifecycle

Tasks are the primary unit of work. Each task has a title, description, and type.

### Create a task

```bash
llmflows task create -t "Title" -d "Description"
llmflows task create -t "Fix bug" -d "Details" --type fix
```

Task types: `feature` (default), `fix`, `refactor`, `chore`.

### Start a run (daemon mode)

The daemon must be running. The run is queued and picked up automatically.

```bash
llmflows task start --id <task-id>
llmflows task start --id <task-id> --flow default
llmflows task start --id <task-id> --flow ripper-5 --flow submit-pr --prompt "Ship it"

# Specify model and agent
llmflows task start --id <task-id> --flow default --model gemini-3-flash
llmflows task start --id <task-id> --flow default --model sonnet-4.6 --agent claude-code
```

### Start a run (inline mode)

No daemon needed. The protocol is printed to stdout for the calling agent.

```bash
# Create task and start run in one command (primary path for cloud VMs)
llmflows task create -t "Title" -d "Description" --inline --flow default
llmflows task create -t "Title" -d "Description" --inline --flow default --no-git

# With model and agent
llmflows task create -t "Title" -d "Description" --inline --model gemini-3-flash --agent cursor

# Re-run an existing task inline (local only — requires persistent DB)
llmflows task start --id <task-id> --inline
```

`--inline` on `task create` both creates the task and immediately starts the run.

Use `--no-git` on cloud VMs or non-git projects to skip worktree creation.

Options for model/agent:
- `--model` / `-m` — model name (e.g. `gemini-3-flash`, `sonnet-4.6`, `sonnet-4.6-thinking`)
- `--agent` / `-a` — agent backend: `cursor`, `claude-code`, `codex`, `qwen-code` (default: `cursor`)

### Monitor runs

```bash
llmflows run list
llmflows run list --task <task-id>
llmflows run show <run-id>
llmflows run logs <run-id> --follow
```

### Update or delete tasks

```bash
llmflows task update --id <task-id> --title "Better title"
llmflows task update --id <task-id> --description "Updated"
llmflows task delete --id <task-id> --yes
```

## Flow Management

Flows define the sequence of steps an agent follows. For step content format, gates, IFs, and flow authoring details, see the `llmflows-flows` skill.

```bash
# List all flows
llmflows flow list

# Show a flow and its steps
llmflows flow show <name>

# List steps with positions
llmflows flow step list --flow <name>

# Create an empty flow
llmflows flow create my-flow --description "What this flow does"

# Duplicate an existing flow
llmflows flow create my-variant --copy-from default

# Add a step from a file (or pipe via stdin)
llmflows flow step add --flow my-flow --name step-name --content step.md
llmflows flow step add --flow my-flow --name step-name --content step.md --position 2

# Edit a step's content
llmflows flow step edit --flow my-flow --name step-name --content updated.md

# Remove a step
llmflows flow step remove --flow my-flow --name step-name

# Export all flows to JSON
llmflows flow export --output flows.json

# Import flows from JSON (upserts by name)
llmflows flow import flows.json

# Delete a flow (cannot delete 'default')
llmflows flow delete my-flow --yes
```

## Aliases

Aliases are project-level presets that bundle agent, model, and flow chain.

```bash
# List aliases
llmflows alias list

# Create/update an alias
llmflows alias set fast --agent cursor --model gemini-3-flash --flow default
llmflows alias set thorough --model sonnet-4.6-thinking --flow ripper-5,submit-pr

# Show details
llmflows alias show fast

# Delete (cannot delete 'default')
llmflows alias delete fast --yes
```

## Daemon

The daemon runs in the background, picks up queued runs, and executes them.

```bash
llmflows daemon start
llmflows daemon status
llmflows daemon stop

# Foreground mode (for debugging)
llmflows daemon start --foreground
```

## Active Agents

```bash
# List running agents
llmflows agent list
llmflows agent list --all

# Stream agent logs
llmflows agent logs <task-id> --follow
llmflows agent logs --run <run-id> --follow
```

## Database

```bash
# Reset database (all data lost — must re-register projects)
llmflows db reset --yes
```

## Typical Agent Workflow

When an agent asks you to set up and run a task via llmflows:

```bash
# 1. Register the project (if not already done)
llmflows register

# 2. Start the daemon
llmflows daemon start

# 3. Create a task
llmflows task create -t "Implement feature X" -d "Detailed description of what to build"

# 4. Start the run (note the task ID from step 3)
llmflows task start --id <task-id> --flow default

# 5. Monitor
llmflows run list --task <task-id>
llmflows run logs <run-id> --follow
```

For inline (no daemon):

```bash
llmflows task create -t "Fix bug" -d "Description" --inline --flow default --no-git
```

## Quick Reference

| Action | Command |
|--------|---------|
| Register project | `llmflows register` |
| List projects | `llmflows project list` |
| Create task | `llmflows task create -t "..." -d "..."` |
| List tasks | `llmflows task list` |
| Start run (daemon) | `llmflows task start --id <id> --flow default` |
| Start run (inline) | `llmflows task start --id <id> --inline` |
| List runs | `llmflows run list` |
| Show run details | `llmflows run show <run-id>` |
| Follow logs | `llmflows run logs <run-id> --follow` |
| List flows | `llmflows flow list` |
| Show flow | `llmflows flow show <name>` |
| Create flow | `llmflows flow create <name>` |
| Add step | `llmflows flow step add --flow <name> --name <step> --content file.md` |
| Export flows | `llmflows flow export --output flows.json` |
| Import flows | `llmflows flow import flows.json` |
| List aliases | `llmflows alias list` |
| Set alias | `llmflows alias set <name> --flow default --model ...` |
| Daemon start | `llmflows daemon start` |
| Daemon status | `llmflows daemon status` |
| Agent logs | `llmflows agent logs <task-id> --follow` |
