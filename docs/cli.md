# CLI Reference

## Project

```bash
# Register the current git repo as a llmflows project
llmflows register
llmflows register --name "My App"

# List all registered projects
llmflows project list

# Rename a project
llmflows project update --name "New Name"
llmflows project update --id <project-id> --name "New Name"

# Unregister a project
llmflows project delete
llmflows project delete --id <project-id>
```

## Tasks

```bash
# List tasks for the current project
llmflows task list

# List tasks across all projects
llmflows task list --all

# Show task details and run history
llmflows task show --id <task-id>

# Create a task (-d is required — becomes the prompt for the first run)
llmflows task create -t "Fix login bug" -d "Safari shows blank page on submit"
llmflows task create -t "Add pagination" -d "Add cursor-based pagination to the posts list" --type feature

# Start a run immediately (inline, no daemon needed — auto-registers the project)
llmflows task create -t "My task" -d "Description" --inline --flow default

# Start inline without creating a git worktree (for cloud agent VMs)
llmflows task create -t "My task" -d "Description" --inline --no-worktree

# Update a task
llmflows task update --id <task-id> --title "Better title"
llmflows task update --id <task-id> --description "Updated description"

# Delete a task
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

# Show run details
llmflows run show <run-id>

# Print logs for a run
llmflows run logs <run-id>
llmflows run logs <run-id> --follow
llmflows run logs <run-id> --raw

# Enqueue a new run for the daemon
llmflows task start --id <task-id>
llmflows task start --id <task-id> --flow ripper-5
llmflows task start --id <task-id> --flow default --prompt "Focus on the mobile layout"

# Chain multiple flows (executed in order)
llmflows task start --id <task-id> --flow ripper-5 --flow submit-pr
llmflows task start --id <task-id> --flow default --flow submit-pr --prompt "Ship it"

# Start inline (no daemon needed)
llmflows task start --id <task-id> --inline
llmflows task start --id <task-id> --inline --no-worktree
llmflows task start --id <task-id> --inline --flow react-js --prompt "Fix the layout"
```

## Flows

```bash
# List all flows
llmflows flow list

# Show a flow and its steps
llmflows flow show <name>

# Create a flow
llmflows flow create <name>
llmflows flow create <name> --description "What this flow does"
llmflows flow create <name> --copy-from default

# Delete a flow
llmflows flow delete <name>
llmflows flow delete <name> --yes

# Export / import
llmflows flow export --output flows.json
llmflows flow import flows.json
```

### Steps

```bash
# List steps in a flow
llmflows flow step list --flow <name>

# Add a step (from file)
llmflows flow step add --flow <name> --name <step-name> --content step.md

# Add a step (from stdin)
cat step.md | llmflows flow step add --flow <name> --name <step-name>

# Add a step at a specific position
llmflows flow step add --flow <name> --name <step-name> --content step.md --position 2

# Edit a step's content
llmflows flow step edit --flow <name> --name <step-name> --content step.md

# Remove a step
llmflows flow step remove --flow <name> --name <step-name>
```

## Daemon

```bash
# Start the daemon (background)
llmflows daemon start

# Start in foreground (logs to terminal + log file)
llmflows daemon start --foreground

# Stop the daemon
llmflows daemon stop

# Show daemon status
llmflows daemon status
```

## Agent (internal)

These commands are called by the agent inside a worktree — not meant for manual use.

```bash
# Load the next step instructions
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

# Custom port
llmflows ui --port 9000

# Auto-reload on code changes
llmflows ui --reload
```

## Database

```bash
# Wipe and recreate the database
llmflows db reset
llmflows db reset --yes
```
