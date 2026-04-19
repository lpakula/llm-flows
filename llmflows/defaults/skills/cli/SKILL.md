---
name: llmflows-cli
description: Use the llmflows CLI to manage spaces, flows, runs, agents, and the daemon. Use when the user wants to register a space, create or schedule runs, manage flows and steps, configure agent aliases, check run status, or perform any llmflows operation from the terminal.
---

# llmflows CLI

llmflows is a workflow orchestrator for autonomous coding agents. All operations available in the web UI can be performed via CLI.

## Prerequisites

- llmflows must be installed (`llmflows --version` to verify)
- For most commands, run from inside a registered space directory
- Register first if needed: `llmflows register`

## Space Setup

```bash
# Register current directory as a space
llmflows register
llmflows register --name "My App"

# List all registered spaces
llmflows space list

# Rename a space
llmflows space update --name "New Name"

# View/update settings
llmflows space settings
llmflows space settings --git-repo false

# Unregister a space
llmflows space delete
llmflows space delete --id <space-id>

# Space variables (available as {{space.<KEY>}} in flows)
llmflows space var set REPOS_PATH /Users/me/repos
llmflows space var list
llmflows space var remove REPOS_PATH
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

## Runs

A run is a single execution of a flow. Use `run schedule` to queue a new run.

```bash
# Schedule a run for a flow
llmflows run schedule --flow <flow-id>
llmflows run schedule --flow <flow-id> --space <space-id>

# List runs
llmflows run list
llmflows run list --all
llmflows run list --space <space-id> --limit 50

# Show run details
llmflows run show <run-id>

# Print / follow logs
llmflows run logs <run-id>
llmflows run logs <run-id> --follow
llmflows run logs <run-id> --raw
```

## Agent Aliases

Aliases are pre-defined tiers (`mini`, `normal`, `max`) that map to an agent backend and model, per type (`pi` for default/hitl steps, `code` for code steps). Managed under `llmflows agent alias`.

```bash
# List all configured aliases
llmflows agent alias list

# Update an alias tier
llmflows agent alias update normal --type pi --agent pi --model anthropic/claude-sonnet-4-5
llmflows agent alias update max --type code --agent claude-code --model opus
```

## Active Agents

```bash
# List running agents for current space
llmflows agent list
llmflows agent list --all

# Stream agent logs for a run
llmflows agent logs <run-id> --follow
llmflows agent logs <run-id> --raw
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

## Web UI

```bash
# Launch web UI
llmflows ui
llmflows ui --port 8080 --host 0.0.0.0

# Dev mode (Vite HMR + FastAPI with auto-reload)
llmflows ui --dev
```

## Typical Workflow

```bash
# 1. Register the space (if not already done)
llmflows register

# 2. Start the daemon
llmflows daemon start

# 3. Schedule a run
llmflows run schedule --flow <flow-id>

# 4. Monitor
llmflows run list
llmflows run logs <run-id> --follow
```

## Quick Reference

| Action | Command |
|--------|---------|
| Register space | `llmflows register` |
| List spaces | `llmflows space list` |
| Delete space | `llmflows space delete` |
| Set variable | `llmflows space var set KEY VALUE` |
| List variables | `llmflows space var list` |
| Remove variable | `llmflows space var remove KEY` |
| List flows | `llmflows flow list` |
| Show flow | `llmflows flow show <name>` |
| Create flow | `llmflows flow create <name>` |
| Add step | `llmflows flow step add --flow <name> --name <step> --content file.md` |
| Export flows | `llmflows flow export --output flows.json` |
| Import flows | `llmflows flow import flows.json` |
| Schedule run | `llmflows run schedule --flow <flow-id>` |
| List runs | `llmflows run list` |
| Show run | `llmflows run show <run-id>` |
| Follow run logs | `llmflows run logs <run-id> --follow` |
| List aliases | `llmflows agent alias list` |
| Update alias | `llmflows agent alias update <tier> --type pi --model ...` |
| List agents | `llmflows agent list` |
| Agent logs | `llmflows agent logs <run-id> --follow` |
| Daemon start | `llmflows daemon start` |
| Daemon status | `llmflows daemon status` |
| Launch UI | `llmflows ui` |
