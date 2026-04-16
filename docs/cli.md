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

# View/update space settings
llmflows space settings
llmflows space settings --id <space-id>
llmflows space settings --git-repo false
```

## Tasks

```bash
# List tasks
llmflows task list
llmflows task list --all
llmflows task list --space <space-id>

# Show one task with run history
llmflows task show --id <task-id>

# Create a task
llmflows task create -t "Fix login bug" -d "Safari shows blank page on submit"
llmflows task create -t "Add pagination" -d "Add cursor-based pagination" --type feature
llmflows task create -t "Fix crash" -d "..." --type fix

# Update a task
llmflows task update --id <task-id> --title "Better title"
llmflows task update --id <task-id> --description "Updated description"

# Delete a task
llmflows task delete --id <task-id>
llmflows task delete --id <task-id> --yes
```

Task types:

- `feature` (default)
- `fix`
- `refactor`
- `chore`

## Start Runs

Use `task start` to enqueue a run for the daemon.

```bash
# Start with the default flow
llmflows task start --id <task-id>

# Pick a flow
llmflows task start --id <task-id> --flow default

# Add a user prompt for this run
llmflows task start --id <task-id> --flow default --prompt "Focus on the mobile layout"

# Pick agent and model
llmflows task start --id <task-id> --flow default --model gemini-3-flash
llmflows task start --id <task-id> --flow default --model sonnet-4.6 --agent claude-code

# Chain multiple flows
llmflows task start --id <task-id> --flow research --flow submit-pr

# Run all steps in one prompt
llmflows task start --id <task-id> --flow default --one-shot
```

`--one-shot` assembles the whole flow into a single agent prompt instead of running one separate agent process per step. This can be useful for strong models when you want fewer agent restarts, but it gives up some of the isolation and step-by-step control of the default mode.

## Runs

```bash
# List runs
llmflows run list
llmflows run list --task <task-id>
llmflows run list --all
llmflows run list --space <space-id>
llmflows run list --limit 50

# Show one run
llmflows run show <run-id>

# Print logs for a run
llmflows run logs <run-id>
llmflows run logs <run-id> --follow
llmflows run logs <run-id> --raw
```

## Flows

```bash
# List/show flows
llmflows flow list
llmflows flow show <name>

# Create or duplicate a flow
llmflows flow create <name>
llmflows flow create <name> --description "What this flow does"
llmflows flow create <name> --copy-from default

# Delete a flow
llmflows flow delete <name>
llmflows flow delete <name> --yes

# Export/import flows as JSON
llmflows flow export
llmflows flow export --output flows.json
llmflows flow import flows.json
```

### Flow Steps

```bash
# List steps
llmflows flow step list --flow <name>

# Add a step from file or stdin
llmflows flow step add --flow <name> --name <step-name> --content step.md
cat step.md | llmflows flow step add --flow <name> --name <step-name>

# Add at a specific position
llmflows flow step add --flow <name> --name <step-name> --content step.md --position 2

# Edit a step from file
llmflows flow step edit --flow <name> --name <step-name> --content step.md

# Remove a step
llmflows flow step remove --flow <name> --name <step-name>
```

Step content is markdown. See [Flow Authoring](flows.md).

## Aliases

Aliases are space-level presets for agent, model, flow chain, and optional per-step overrides.

```bash
# List/show aliases
llmflows alias list
llmflows alias list --space <space-id>
llmflows alias show <name>
llmflows alias show <name> --space <space-id>

# Create or update aliases
llmflows alias set fast --agent cursor --model sonnet-4.6 --flow default
llmflows alias set thorough --model sonnet-4.6-thinking --flow react-js,submit-pr
llmflows alias set default --model sonnet-4.6-thinking

# Per-step overrides
llmflows alias set default -s "default/research:claude-code:sonnet"
llmflows alias set default -s "default/test:qwen:qwen3-coder"

# Clear all step overrides
llmflows alias set default --clear-overrides

# Delete an alias
llmflows alias delete <name>
llmflows alias delete <name> --yes
```

`alias set` options:

- `--agent` / `-a` - agent name (`cursor`, `claude-code`, `codex`, `qwen`)
- `--model` / `-m` - model name
- `--flow` / `-f` - comma-separated flow chain, for example `default,submit-pr`
- `--step-override` / `-s` - `flow/step:agent:model`
- `--clear-overrides` - remove all step overrides

## Agents

View active agents and stream their logs.

```bash
llmflows agent list
llmflows agent list --all

# Stream logs for a task (active or latest run)
llmflows agent logs <task-id>
llmflows agent logs <task-id> --follow
llmflows agent logs <task-id> --raw

# Stream logs for a specific run
llmflows agent logs --run <run-id>
llmflows agent logs --run <run-id> --follow
```

## Daemon

The daemon picks up queued runs and executes them.

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
```

## Database

```bash
llmflows db reset
llmflows db reset --yes
```

---

## Common Workflows

### Create a task, then start a run

```bash
llmflows task create -t "Add dark mode" -d "Add dark mode toggle to settings"
llmflows task start --id <task-id> --flow default
llmflows run list --task <task-id>
llmflows run logs <run-id> --follow
```

### Chain flows

```bash
llmflows task start --id <task-id> --flow research --flow submit-pr --prompt "Ship it"
```

### Build a custom flow from scratch

```bash
llmflows flow create my-flow --description "Custom workflow"
llmflows flow step add --flow my-flow --name research --content steps/research.md --position 0
llmflows flow step add --flow my-flow --name execute --content steps/execute.md --position 1
llmflows flow step add --flow my-flow --name test --content steps/test.md --position 2
llmflows flow show my-flow
llmflows task start --id <task-id> --flow my-flow
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
