---
name: find-skills
description: Find and use bundled llmflows skills for flow creation, CLI usage, connectors, GitHub integration, and more. Use when the user asks about creating flows, configuring connectors, using the CLI, GitHub channel setup, or any llmflows-related task where a bundled skill might help.
---

# Finding llmflows Skills

Bundled skills live in `llmflows/defaults/skills/`. Before starting an llmflows-related task, check if a relevant skill exists and read it for up-to-date guidance.

## Available skills

| Skill | Path | When to use |
|-------|------|-------------|
| **overview** | `llmflows/defaults/skills/overview/SKILL.md` | User asks what llm-flows is, how it works, or needs a platform overview |
| **flows** | `llmflows/defaults/skills/flows/SKILL.md` | Creating or editing flow definitions, steps, gates, conditions |
| **cli** | `llmflows/defaults/skills/cli/SKILL.md` | Managing flows, runs, schedules, tools, and variables via CLI |
| **connectors** | `llmflows/defaults/skills/connectors/SKILL.md` | Setting up Google Workspace, YouTube, Notion, GitHub, Slack, Linear, Postgres connectors |
| **github** | `llmflows/defaults/skills/github/SKILL.md` | Building flows triggered by GitHub issues/PR comments, `@llmflows` mentions |
| **skills** | `llmflows/defaults/skills/skills/SKILL.md` | Creating and managing skills for llm-flows spaces |

## How to use

1. Read the relevant `SKILL.md` file before starting work
2. Follow the instructions inside — they contain the most current patterns and examples
3. Multiple skills can apply to a single task (e.g. **flows** + **github** when building a GitHub-triggered flow)
