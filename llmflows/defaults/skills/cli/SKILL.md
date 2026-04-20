---
name: llmflows-cli
description: Manage flows, runs, schedules, tools, and variables via the llmflows CLI. Use when you need to import, export, update, or inspect flows, configure schedules, enable tools, set variables, or check run status.
---

# llmflows CLI

## Flows

```bash
llmflows flow list                           # List all flows
llmflows flow show <name>                    # Show flow details and steps
llmflows flow create <name> -d "description" # Create a new flow
llmflows flow export --output flows.json     # Export all flows to JSON
llmflows flow import flows/<file>.json       # Import flows (upserts by name)
llmflows flow delete <name>                  # Delete a flow
```

### Creating and updating flows

1. Write the flow JSON to the `flows/` directory
2. Import with `llmflows flow import flows/<filename>.json`
3. Re-importing updates existing flows (upsert by name)

See the `llmflows-flows` skill for step structure, gates, IFs, and examples.

## Flow Settings

```bash
llmflows flow update <name> --description "New description"
llmflows flow update <name> --max-spend 5.0
llmflows flow update <name> --max-concurrent-runs 2
llmflows flow update <name> --rename new-name
```

## Schedules

```bash
llmflows flow schedule <name>                # View current schedule
llmflows flow schedule <name> --cron "0 9 * * 1-5" --timezone US/Eastern --enable
llmflows flow schedule <name> --disable
llmflows flow schedule <name> --clear        # Remove schedule entirely
```

### Common cron patterns

| Schedule | Cron |
|----------|------|
| Every hour | `0 * * * *` |
| Every 6 hours | `0 */6 * * *` |
| Daily at 9am | `0 9 * * *` |
| Weekdays at 9am | `0 9 * * 1-5` |
| Weekly Monday 9am | `0 9 * * 1` |

## Flow Tools

Control which tools are available to agents running a flow.

```bash
llmflows flow tools list <name>              # List tools enabled for flow
llmflows flow tools add <name> web_search    # Enable a tool
llmflows flow tools remove <name> browser    # Remove a tool
```

Available tools: `web_search`, `browser`

## Flow Variables

Flow-level variables accessible as `{{flow.KEY}}` in steps.

```bash
llmflows flow var set <name> KEY VALUE
llmflows flow var list <name>
llmflows flow var remove <name> KEY
```

## Global Tools

```bash
llmflows tools list                          # List all tools and status
llmflows tools enable web_search             # Enable a tool globally
llmflows tools disable browser               # Disable a tool globally
```

## Runs

```bash
llmflows run schedule --flow <flow-id>       # Schedule a run
llmflows run list                            # List runs
llmflows run show <run-id>                   # Show run details
llmflows run logs <run-id> --follow          # Follow logs in real time
```

## Space Variables

Space-level variables accessible as `{{space.KEY}}` in all flows.

```bash
llmflows space var set KEY VALUE
llmflows space var list
llmflows space var remove KEY
```
