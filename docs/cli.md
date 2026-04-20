# CLI Reference

All `llmflows` commands. Run them inside a registered space unless noted otherwise.

## Version

```bash
llmflows --version
```

## Register

Register the current directory as a space and create `.llmflows/`.

```bash
llmflows register
llmflows register --name "My App"
```

## Space

```bash
# List registered spaces
llmflows space list

# Rename a space
llmflows space update --name "New Name"
llmflows space update --id <space-id> --name "New Name"

# Unregister a space
llmflows space delete
llmflows space delete --id <space-id>

# View space settings
llmflows space settings
```

### Space Variables

Variables are available as `{{space.<KEY>}}` in flow step content, gates, and IFs.

```bash
# Set a variable
llmflows space var set API_KEY sk-abc123
llmflows space var set REPOS_PATH /Users/me/repos

# List all variables
llmflows space var list

# Remove a variable
llmflows space var remove API_KEY
```

## Flows

```bash
# List all flows
llmflows flow list

# Show a flow and its steps
llmflows flow show <name>

# Create or duplicate a flow
llmflows flow create <name>
llmflows flow create <name> --description "What this flow does"
llmflows flow create <name> --copy-from default

# Delete a flow
llmflows flow delete <name>
llmflows flow delete <name> --yes

# Export all flows to JSON
llmflows flow export
llmflows flow export --output flows.json

# Import flows from JSON (upserts by name)
llmflows flow import flows.json
```

### Flow Steps

```bash
# List steps in a flow
llmflows flow step list --flow <name>

# Add a step from a file (or pipe via stdin)
llmflows flow step add --flow <name> --name <step-name> --content step.md
cat step.md | llmflows flow step add --flow <name> --name <step-name>

# Add at a specific position
llmflows flow step add --flow <name> --name <step-name> --content step.md --position 2

# Edit a step's content
llmflows flow step edit --flow <name> --name <step-name> --content updated.md

# Remove a step
llmflows flow step remove --flow <name> --name <step-name>
```

## Runs

```bash
# Schedule a new run for a flow
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

## Agents

```bash
# List active agents for the current space
llmflows agent list
llmflows agent list --all

# Stream agent logs for a run
llmflows agent logs <run-id>
llmflows agent logs <run-id> --follow
llmflows agent logs <run-id> --raw
```

### Agent Aliases

Aliases are pre-defined tiers (`mini`, `normal`, `max`) that map to an agent backend and model. Each tier exists per type: `pi` (for agent/hitl steps) and `code` (for code steps).

```bash
# List all configured aliases
llmflows agent alias list
llmflows agent alias list --type pi

# Update an alias
llmflows agent alias update normal --type pi --agent pi --model anthropic/claude-sonnet-4-5
llmflows agent alias update max --type code --agent claude-code --model opus
```

## Daemon

The daemon runs in the background, picks up queued runs, and executes them.

```bash
llmflows daemon start
llmflows daemon start --foreground
llmflows daemon stop
llmflows daemon status
```

## UI

```bash
llmflows ui
llmflows ui --port 9000
llmflows ui --host 0.0.0.0
llmflows ui --reload

# Dev mode (Vite HMR + FastAPI with auto-reload)
llmflows ui --dev
```

---

## Common Workflows

### Register a space and run a flow

```bash
llmflows register
llmflows daemon start
llmflows run schedule --flow <flow-id>
llmflows run list
llmflows run logs <run-id> --follow
```

### Build a custom flow from scratch

```bash
llmflows flow create my-flow --description "Custom workflow"
llmflows flow step add --flow my-flow --name research --content steps/research.md --position 0
llmflows flow step add --flow my-flow --name execute --content steps/execute.md --position 1
llmflows flow show my-flow
llmflows run schedule --flow <flow-id>
```

### Duplicate and customize a flow

```bash
llmflows flow create my-variant --copy-from default --description "Default + extra validation"
llmflows flow step add --flow my-variant --name lint --content steps/lint.md --position 3
```

### Export/import flows between machines

```bash
llmflows flow export --output my-flows.json
llmflows flow import my-flows.json
```

### Set space variables for a flow

```bash
llmflows space var set TARGET_URL https://example.com
llmflows space var set USERNAME admin
llmflows space var set PASSWORD secret123
llmflows space var list
```

## Quick Reference

| Action | Command |
|--------|---------|
| Register space | `llmflows register` |
| List spaces | `llmflows space list` |
| Rename space | `llmflows space update --name "New Name"` |
| Delete space | `llmflows space delete` |
| Set variable | `llmflows space var set KEY VALUE` |
| List variables | `llmflows space var list` |
| Remove variable | `llmflows space var remove KEY` |
| List flows | `llmflows flow list` |
| Show flow | `llmflows flow show <name>` |
| Create flow | `llmflows flow create <name>` |
| Delete flow | `llmflows flow delete <name> --yes` |
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
