---
name: llmflows-flows
description: Create and edit llmflows flow definitions. Use when the user wants to create a new flow, modify flow steps, or asks about flow JSON format, step content structure, or flow best practices.
---

# llmflows Flows

A flow is an ordered list of steps (markdown prompts) that an agent executes sequentially. The agent receives one step at a time, follows the instructions, then advances.

## Flow JSON Format

Flow files live in `flows/` at the project root.

```json
{
  "version": 1,
  "flows": [
    {
      "name": "my-flow",
      "description": "Short description of what this flow does.",
      "steps": [
        {
          "name": "step-name",
          "position": 0,
          "content": "# STEP TITLE\n\n## PURPOSE\n\nWhat this step achieves.\n\n## WORKFLOW\n\n1. First action\n2. Second action\n\n## FORBIDDEN\n\n- Things the agent must not do"
        }
      ]
    }
  ]
}
```

One flow per file in the library, file named after the flow. Positions must be sequential starting at 0.

## IF Conditions

IFs are optional shell commands on a step that control whether the step is included. When `llmflows mode next` is about to enter a step, it evaluates all `ifs` commands. If **any** command exits non-zero, the step is **skipped** and the runner advances to the next step.

```json
{
  "name": "lint",
  "position": 2,
  "content": "# LINT\n\n...",
  "ifs": [
    {"command": "test -f package.json", "message": "Node project exists"},
    {"command": "grep -q eslint package.json", "message": "ESLint is configured"}
  ]
}
```

Each entry has `command` (shell command, must exit 0 for step to run) and `message` (human-readable description). IFs are optional — omit or use `[]` for unconditional steps.

Multiple consecutive steps with failing IFs are all skipped. If all remaining steps are skipped, the flow advances to the next flow in the chain or completes.

**IF vs Gates**: IFs decide whether to *enter* a step. Gates block you from *leaving* a step. Use IFs for conditional inclusion; use gates for enforcing completion.

## Gates

Gates are optional shell commands on a step that `llmflows mode next` enforces before advancing. If any gate command exits non-zero, the agent is blocked and shown the failure.

```json
{
  "name": "test",
  "position": 1,
  "content": "# TEST\n\n...",
  "gates": [
    {"command": "test -f .llmflows/screenshots/homepage.png", "message": "Screenshot exists"},
    {"command": "npm test -- --watchAll=false", "message": "Tests pass"}
  ]
}
```

Each gate has `command` (shell command, must exit 0) and `message` (human-readable failure feedback sent to the agent). Gates are optional — omit or use `[]` for no enforcement.

IF commands, gate commands, messages, and step content support template variables: `{{run.id}}`, `{{task.id}}`, `{{flow.name}}`. These are resolved at runtime.

## Step Content Conventions

Each step's `content` is a markdown prompt with these sections:

| Section | Required | Purpose |
|---------|----------|---------|
| `# TITLE` | Yes | Step name in uppercase |
| `## PURPOSE` | Yes | One-sentence goal |
| `## WORKFLOW` | Yes | Numbered action list |
| `## PERMITTED` | No | Explicitly allowed actions |
| `## FORBIDDEN` | No | Hard constraints |
| `## RULES` | No | Output format or quality rules |

## Best Practices

**Constraint progression** — tighten permissions as the flow advances:
- Early steps (research/plan): "No code changes to project files", "No git operations"
- Execute steps: "No git operations", "No scope expansion"
- Commit/final steps: "Do not push"

**Step granularity** — each step should have a single clear purpose. If a step has two unrelated goals, split it.

**Artifacts** — if steps need to share state, use a file (e.g. `.llmflows/task.md`). Early steps write findings; later steps read them.

**Keep steps self-contained** — the agent only sees one step at a time. Each step must include all context needed to execute it.

## Creating a New Flow

1. **Clarify the workflow** — what stages should the agent go through?
2. **Create the JSON file** in `flows/<name>.json`
3. **Write each step** following the content conventions above
4. **Set constraints** — apply the constraint progression pattern

## Modifying an Existing Flow

1. **Read the current flow** — check `flows/` for existing flow files
2. **Edit the JSON file** directly

## Reference Flows

Study existing flows for patterns:
- `flows/ripper-5.json` — full 7-step research-driven flow with artifact passing
- `flows/react-js.json` — 4-step flow: execute, test dev server, take & verify screenshots, commit
