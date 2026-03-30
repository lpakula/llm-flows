# CLI Reference

All `llmflows` commands. Run from inside a registered project directory unless noted otherwise.

## Version

```bash
llmflows --version
```

## Register

Register the current directory as a llmflows project. Must be run once before using other commands.

```bash
# Register with auto-detected name (directory name)
llmflows register

# Register with a custom name
llmflows register --name "My App"
```

Auto-creates `.llmflows/` directory. 

## Project

```bash
# List all registered projects
llmflows project list

# Rename a project (defaults to current directory)
llmflows project update --name "New Name"
llmflows project update --id <project-id> --name "New Name"

# Unregister a project
llmflows project delete
llmflows project delete --id <project-id>

# View project settings
llmflows project settings
llmflows project settings --id <project-id>

# Mark project as non-git (disables worktrees)
llmflows project settings --git-repo false
```

## Tasks

```bash
# List tasks for the current project
llmflows task list

# List tasks across all projects
llmflows task list --all

# List tasks for a specific project (from anywhere)
llmflows task list --project <project-id>

# Show task details and run history
llmflows task show --id <task-id>

# Create a task
llmflows task create -t "Fix login bug" -d "Safari shows blank page on submit"
llmflows task create -t "Add pagination" -d "Add cursor-based pagination" --type feature

# Task types: feature (default), fix, refactor, chore
llmflows task create -t "Fix crash" -d "..." --type fix

# Create task and start a run immediately (inline, no daemon needed — auto-registers the project)
llmflows task create -t "My task" -d "Description" --inline --flow default

# Same, without creating a git worktree (for cloud agent VMs)
llmflows task create -t "My task" -d "Description" --inline --no-git

# Specify model and agent
llmflows task create -t "My task" -d "Description" --inline --model gemini-3-flash --agent cursor

# Update a task
llmflows task update --id <task-id> --title "Better title"
llmflows task update --id <task-id> --description "Updated description"

# Delete a task (and all its runs)
llmflows task delete --id <task-id>
llmflows task delete --id <task-id> --yes
```

## Runs

```bash
# List runs for the current project
llmflows run list

# List runs for a specific task
llmflows run list --task <task-id>

# List runs across all projects
llmflows run list --all

# List runs for a specific project (from anywhere)
llmflows run list --project <project-id>

# Limit number of results (default: 20)
llmflows run list --limit 50

# Show run details (status, flow, step, prompt, summary)
llmflows run show <run-id>

# Print logs for a run
llmflows run logs <run-id>
llmflows run logs <run-id> --follow
llmflows run logs <run-id> --raw

# Enqueue a new run for the daemon
llmflows task start --id <task-id>
llmflows task start --id <task-id> --flow default
llmflows task start --id <task-id> --flow default --prompt "Focus on the mobile layout"

# Specify model and agent
llmflows task start --id <task-id> --flow default --model gemini-3-flash
llmflows task start --id <task-id> --flow default --model sonnet-4.6 --agent claude-code

# Chain multiple flows (executed in order)
llmflows task start --id <task-id> --flow ripper-5 --flow submit-pr
llmflows task start --id <task-id> --flow default --flow submit-pr --prompt "Ship it"

# Re-run an existing task inline (no daemon needed, requires persistent DB)
llmflows task start --id <task-id> --inline
llmflows task start --id <task-id> --inline --flow react-js --prompt "Fix the layout"
```

## Flows

```bash
# List all flows with step counts
llmflows flow list

# Show a flow and its steps
llmflows flow show <name>

# Create an empty flow
llmflows flow create <name>
llmflows flow create <name> --description "What this flow does"

# Duplicate an existing flow
llmflows flow create <name> --copy-from default

# Delete a flow (cannot delete 'default')
llmflows flow delete <name>
llmflows flow delete <name> --yes

# Export all flows to JSON
llmflows flow export
llmflows flow export --output flows.json

# Import flows from a JSON file (upserts by name)
llmflows flow import flows.json
```

### Steps

```bash
# List steps in a flow (with positions and IDs)
llmflows flow step list --flow <name>

# Add a step (from file)
llmflows flow step add --flow <name> --name <step-name> --content step.md

# Add a step (from stdin)
cat step.md | llmflows flow step add --flow <name> --name <step-name>

# Add a step at a specific position
llmflows flow step add --flow <name> --name <step-name> --content step.md --position 2

# Edit a step's content (from file)
llmflows flow step edit --flow <name> --name <step-name> --content step.md

# Remove a step
llmflows flow step remove --flow <name> --name <step-name>
```

**Step content** is a markdown file. See [Flow Authoring](flows.md) for the format.

## Aliases

Aliases are project-level configuration presets that bundle an agent, model, and flow chain into a named shortcut. Useful for GitHub integration triggers (e.g. `@llmflows --alias fast`).

```bash
# List all aliases for the current project
llmflows alias list
llmflows alias list --project <project-id>

# Show details of a specific alias
llmflows alias show <name>
llmflows alias show <name> --project <project-id>

# Create or update an alias
llmflows alias set fast --agent cursor --model sonnet-4.6 --flow default
llmflows alias set thorough --model sonnet-4.6-thinking --flow react-js,submit-pr
llmflows alias set default --model sonnet-4.6-thinking

# Delete an alias (cannot delete 'default')
llmflows alias delete <name>
llmflows alias delete <name> --yes
```

Options for `alias set`:
- `--agent` / `-a` — agent name (e.g. `cursor`, `claude`)
- `--model` / `-m` — model name
- `--flow` / `-f` — comma-separated flow chain (e.g. `default,submit-pr`)

## Agents

View active agents and stream their logs.

```bash
# List active agents for the current project
llmflows agent list

# List active agents across all projects
llmflows agent list --all

# Stream logs for a task (finds active or latest run)
llmflows agent logs <task-id>
llmflows agent logs <task-id> --follow
llmflows agent logs <task-id> --raw

# Stream logs for a specific run
llmflows agent logs --run <run-id>
llmflows agent logs --run <run-id> --follow
```

## Daemon

The daemon is a background service that picks up queued runs and executes them.

```bash
# Start the daemon (background)
llmflows daemon start

# Start in foreground (logs to terminal + log file)
llmflows daemon start --foreground

# Stop the daemon
llmflows daemon stop

# Show daemon status (running/stopped, PID)
llmflows daemon status
```

## Agent Protocol (internal)

These commands are called by the agent inside a worktree during flow execution — not for manual use.

```bash
# Load the next step instructions (enforces gates before advancing)
llmflows mode next

# Re-read the current step (after crash or restart)
llmflows mode current

# Save run summary (called by the complete step)
llmflows run complete --summary "$(cat <<'EOF'
## What was done
...
EOF
)"
```

## UI

```bash
# Start the web UI
llmflows ui

# Custom host and port
llmflows ui --port 9000
llmflows ui --host 0.0.0.0

# Auto-reload on code changes (development)
llmflows ui --reload
```

## Database

```bash
# Wipe and recreate the database (all data lost)
llmflows db reset
llmflows db reset --yes
```

---

## Common Workflows

### Create a task and run it immediately (no daemon)

```bash
llmflows task create -t "Fix login bug" -d "Safari shows blank page" --inline --flow default
```

### Create a task, then start a run via daemon

```bash
llmflows task create -t "Add dark mode" -d "Add dark mode toggle to settings"
# Note the task ID from output, then:
llmflows task start --id <task-id> --flow default
llmflows run list --task <task-id>
llmflows run logs <run-id> --follow
```

### Chain flows

```bash
llmflows task start --id <task-id> --flow ripper-5 --flow submit-pr --prompt "Ship it"
```

### Build a custom flow from scratch

```bash
# Create empty flow
llmflows flow create my-flow --description "Custom workflow"

# Add steps from markdown files
llmflows flow step add --flow my-flow --name understand --content steps/understand.md --position 0
llmflows flow step add --flow my-flow --name implement --content steps/implement.md --position 1
llmflows flow step add --flow my-flow --name validate  --content steps/validate.md  --position 2

# Verify
llmflows flow show my-flow

# Use it
llmflows task start --id <task-id> --flow my-flow
```

### Duplicate and customize a flow

```bash
llmflows flow create my-variant --copy-from default --description "Default + extra validation"
llmflows flow step add --flow my-variant --name lint --content steps/lint.md --position 3
```

### Export/import flows between machines

```bash
# Export on machine A
llmflows flow export --output my-flows.json

# Import on machine B
llmflows flow import my-flows.json
```
