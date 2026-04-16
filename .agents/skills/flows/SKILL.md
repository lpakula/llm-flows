---
name: llmflows-flows
description: Create and edit llmflows flow definitions. Use when the user wants to create a new flow, modify flow steps, edit step content, add gates or conditions, or asks about flow structure, step content format, or flow best practices.
---

# llmflows Flows

A flow is an ordered list of steps (markdown prompts) that `llm-flows` executes sequentially. Each step runs as a separate agent run orchestrated by the daemon. Each step can have gates (must-pass checks) and IFs (conditional inclusion).

## Creating Flows via CLI

### Create an empty flow

```bash
llmflows flow create my-flow --description "What this flow does"
```

### Duplicate an existing flow

```bash
llmflows flow create my-variant --copy-from default --description "Default with extra validation"
```

### Add steps from files

Write each step as a `.md` file, then add them in order:

```bash
llmflows flow step add --flow my-flow --name understand --content steps/understand.md --position 0
llmflows flow step add --flow my-flow --name implement --content steps/implement.md --position 1
llmflows flow step add --flow my-flow --name validate  --content steps/validate.md  --position 2
```

### Add steps from stdin

```bash
cat <<'EOF' | llmflows flow step add --flow my-flow --name understand
# UNDERSTAND

## PURPOSE

Inspect the task and understand the relevant code before making any changes.

## WORKFLOW

1. Read the task description carefully
2. Identify relevant files and modules
3. Read through the relevant code

## RULES

- Do not make any code changes in this step
EOF
```

### Edit a step

```bash
llmflows flow step edit --flow my-flow --name understand --content updated-step.md
```

### Remove a step

```bash
llmflows flow step remove --flow my-flow --name old-step
```

### Inspect flows and steps

```bash
llmflows flow list
llmflows flow show my-flow
llmflows flow step list --flow my-flow
```

## Step Content Format

Each step's `content` is a markdown prompt. Use these sections:

| Section | Required | Purpose |
|---------|----------|---------|
| `# TITLE` | Yes | Step name in uppercase |
| `## PURPOSE` | Yes | One-sentence goal |
| `## WORKFLOW` | Yes | Numbered action list |
| `## PERMITTED` | No | Explicitly allowed actions |
| `## FORBIDDEN` | No | Hard constraints |
| `## RULES` | No | Output format or quality rules |

### Example step content

```markdown
# IMPLEMENT

## PURPOSE

Make the changes described in the task.

## WORKFLOW

1. Implement the changes based on your understanding from the previous step
2. Follow the conventions and patterns found in the codebase
3. Keep changes minimal and focused on the task

## RULES

- No scope expansion beyond what was asked

## FORBIDDEN

- No git operations
```

## Gates

Gates are shell commands that must exit 0 before the agent can advance past a step. If a gate fails, the agent sees the error and must fix the problem. There is no way to skip a gate.

Gates are defined in the flow JSON structure, not in the step markdown content.

### Adding gates via export/import

```bash
# Export flows to JSON
llmflows flow export --output flows.json
```

Edit the JSON to add gates to a step:

```json
{
  "name": "test",
  "position": 1,
  "content": "# TEST\n\n## PURPOSE\n\nRun the test suite.\n\n## WORKFLOW\n\n1. Run tests\n2. Fix failures\n3. Re-run until all pass",
  "gates": [
    {"command": "npm test -- --watchAll=false", "message": "Tests must pass before advancing."},
    {"command": "npm run build", "message": "Build must succeed."}
  ]
}
```

```bash
# Import back (upserts by name)
llmflows flow import flows.json
```

Each gate has:
- `command` — shell command that must exit 0
- `message` — human-readable failure feedback shown to the agent

## IF Conditions

IFs are optional shell commands that control whether a step is included. Before entering a step, `llm-flows` evaluates all `ifs`. If **any** command exits non-zero, the step is **skipped**.

```json
{
  "name": "lint-js",
  "position": 2,
  "content": "# LINT\n\n...",
  "ifs": [
    {"command": "test -f package.json", "message": "Node project exists"},
    {"command": "grep -q eslint package.json", "message": "ESLint is configured"}
  ]
}
```

**IF vs Gates**: IFs decide whether to *enter* a step. Gates block you from *leaving* a step.

## Template Variables

Step content, gate commands, gate messages, and IF commands support template variables:

- `{{run.id}}` — current run ID
- `{{task.id}}` — current task ID
- `{{flow.name}}` — current flow name
- `{{artifacts_dir}}` — absolute path where this step should write output files (screenshots, reports, etc.)
- `{{space.<KEY>}}` — space-level variable (set via `llmflows space var set KEY VALUE`)

### Space variables

Space variables are key-value pairs stored in the database and available to all flows. They are interpolated before shell execution, so they work in gate commands, IF commands, and step content.

```bash
# Set a variable
llmflows space var set REPOS_PATH /Users/me/repos
llmflows space var set DEFAULT_ORG mycompany

# List all variables
llmflows space var list

# Remove a variable
llmflows space var remove REPOS_PATH
```

Use in gates and step content as `{{space.REPOS_PATH}}`:

```json
{
  "command": "test -d {{space.REPOS_PATH}}/my-service/.worktrees/task-{{task.id}}",
  "message": "Worktree not found."
}
```

Artifacts from completed steps are automatically collected and passed as context to subsequent steps.

Example usage in a gate:

```json
{
  "command": "ls {{artifacts_dir}}/*.png 2>/dev/null | grep -q .",
  "message": "No screenshots found. Save at least one .png to {{artifacts_dir}}/ before advancing."
}
```

## Step Types

Each step has a `step_type` that controls how the daemon handles it after the agent finishes.

### `"agent"` (default)

A normal agent step. The agent runs the prompt, and when it finishes the daemon evaluates gates. If gates pass, the flow advances to the next step automatically.

### `"manual"`

A step where the agent prepares output and then **pauses for user input**. The agent runs the prompt content as usual (e.g. proposing multiple implementation approaches, preparing a review checklist), but when the agent finishes, the daemon marks the step as "awaiting user" instead of evaluating gates. The step appears in the **Inbox** with a text input field where the user can respond before the flow continues. The user's response is passed to the **next** step as context.

Use `"manual"` when the flow needs a human decision or action before proceeding -- e.g. choosing between approaches, approving a plan, visual review, manual QA, or providing additional input.

```json
{
  "name": "propose-solutions",
  "position": 0,
  "step_type": "manual",
  "agent_alias": "high",
  "content": "# PROPOSE SOLUTIONS\n\n## PURPOSE\n\nAnalyze the task and propose 2-3 approaches for the user to choose from.\n\n## WORKFLOW\n\n1. Explore the codebase\n2. Think of 2-3 distinct approaches\n3. Present them numbered and ask which one to implement"
}
```

### How manual steps flow

1. The daemon launches the agent with the step's content (same as `"agent"`)
2. The agent runs and produces output (e.g. a proposal or checklist)
3. When the agent finishes, instead of evaluating gates, the daemon marks the step as **awaiting user**
4. The step appears in the **Inbox** with the agent's output and a text input field
5. The user reads the output and submits a response
6. The daemon marks the step as completed and advances to the next step
7. The next step receives the user's response as part of its context

**One-shot mode is automatically disabled** when a flow contains any `"manual"` steps, since one-shot combines all steps into a single agent run and cannot pause for user input.

## Step Fields

Each step supports these fields in the JSON format:

| Field | Default | Purpose |
|-------|---------|---------|
| `name` | required | Step identifier |
| `position` | required | Sequential index starting at 0 |
| `content` | required | Markdown prompt |
| `step_type` | `"agent"` | Step type: `"agent"` or `"manual"` |
| `agent_alias` | `"standard"` | Which agent config to use (e.g. `"fast"`, `"standard"`, `"high"`) |
| `allow_max` | `false` | On the last gate retry, escalate to max-capability model |
| `max_gate_retries` | `3` | How many times to retry a failed gate before failing the step |
| `gates` | `[]` | Shell commands that must pass to advance |
| `ifs` | `[]` | Shell commands that must pass to enter the step |

**Agent aliases** map to agent configurations defined in Settings. Use `"fast"` for simple steps (init, commit), `"standard"` for most steps, `"high"` for complex reasoning steps (brainstorm, plan, execute). Enable `allow_max` on execute/test steps where a final escalation attempt is worth it.

## Flow JSON Format

The export/import format. One file can contain multiple flows.

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
          "step_type": "agent",
          "agent_alias": "standard",
          "allow_max": false,
          "max_gate_retries": 3,
          "content": "# STEP TITLE\n\n## PURPOSE\n\n...\n\n## WORKFLOW\n\n1. ...",
          "gates": [],
          "ifs": []
        }
      ]
    }
  ]
}
```

Positions must be sequential starting at 0. Fields at their default values can be omitted.

## Best Practices

**Constraint progression** — tighten permissions as the flow advances:
- Early steps (research/plan): "No code changes to project files", "No git operations"
- Execute steps: "No git operations", "No scope expansion"
- Commit/final steps: "Do not push"

**Step granularity** — each step should have a single clear purpose. If a step has two unrelated goals, split it.

**Artifacts** — if steps need to share state, use a file (e.g. `.llmflows/task.md`). Early steps write findings; later steps read them.

**Attachments** — to publish files (screenshots, images, reports) so they appear in the task UI and run summary, save them to `{{artifacts_dir}}/attachments/`. When a step completes, the daemon automatically copies files from this subdirectory to the task's shared attachments. Image attachments (`.png`, `.jpg`, `.gif`, `.webp`) are rendered inline in the run summary with click-to-zoom; other file types appear as download links.

**Keep steps self-contained** — the agent only sees one step at a time. Each step must include all context needed to execute it.

**Use gates for deterministic checks** — builds, test suites, file existence, commit status. Don't use gates for subjective checks.

**Use IFs for conditional steps** — skip language-specific steps when that language isn't present, skip screenshot steps when there's no UI.

**Match agent alias to step complexity** — `"fast"` for trivial steps (init, commit), `"standard"` for most steps, `"high"` for steps requiring deep reasoning (brainstorm, plan, complex execute).

**Enable `allow_max` on steps that retry gates** — only useful when `max_gate_retries > 1`. On the last retry the daemon escalates to max capability, giving the agent one final strong attempt to fix the problem. Typically set on execute and test steps.

## Creating a New Flow (step by step)

1. **Clarify the workflow** — what stages should the agent go through?
2. **Create the flow**:
   ```bash
   llmflows flow create my-flow --description "Description"
   ```
3. **Write each step** as a markdown file following the content format above
4. **Add steps**:
   ```bash
   llmflows flow step add --flow my-flow --name step-name --content step.md --position 0
   ```
5. **Add gates/IFs** (if needed) via export/import:
   ```bash
   llmflows flow export --output flows.json
   # Edit flows.json to add gates/ifs
   llmflows flow import flows.json
   ```
6. **Verify**:
   ```bash
   llmflows flow show my-flow
   ```

## Modifying an Existing Flow

```bash
# View current state
llmflows flow show my-flow
llmflows flow step list --flow my-flow

# Edit a step's content
llmflows flow step edit --flow my-flow --name step-name --content updated.md

# Add a new step
llmflows flow step add --flow my-flow --name new-step --content new.md --position 3

# Remove a step
llmflows flow step remove --flow my-flow --name old-step

# For gates/IFs changes, use export/import
llmflows flow export --output flows.json
# Edit flows.json
llmflows flow import flows.json
```

## Reference Flows

Built-in flows (seeded on first run):
- **`default`** — 3-step: understand, implement, validate
- **`submit-pr`** — 1-step: push branch and create/comment on PR (gated on push)

Example flows in `flows/` directory:
- **`ripper-5`** — 7-step research-driven flow with artifact passing and multiple gates
- **`react-js`** — 6-step flow demonstrating prompt/manual steps: propose solutions (prompt) → execute → validate (gated) → take screenshots (gated) → manual review (manual) → commit (gated)

Study these for patterns. Export them to see the full JSON:

```bash
llmflows flow export | python -m json.tool
```

## Flow Chaining

Multiple flows can be chained to run in sequence:

```bash
llmflows task start --id <task-id> --flow ripper-5 --flow submit-pr
```

When the last step of the first flow completes, the agent automatically advances to the first step of the next flow.
