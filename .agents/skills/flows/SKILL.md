---
name: llmflows-flows
description: Create and edit llmflows flow definitions. Use when the user wants to create a new flow, modify flow steps, edit step content, add gates or conditions, or asks about flow structure, step content format, or flow best practices.
---

# llmflows Flows

A flow is an ordered list of steps that `llm-flows` executes sequentially. Each step runs as a separate agent run orchestrated by the daemon. Steps produce artifacts that are automatically passed as context to subsequent steps. Each step can have gates (must-pass checks) and IFs (conditional inclusion).

---

## Core Concepts

### How a flow runs

1. The daemon picks the first step and evaluates its **IF conditions**
2. If IFs pass (or there are none), the step is launched
3. The agent/executor runs the step content and produces artifacts
4. The daemon evaluates **gates** — shell commands that must exit 0
5. If all gates pass, the daemon advances to the next step
6. If a gate fails, the agent is relaunched with failure context to fix the problem
7. After the last step, an automatic `__summary__` step runs to produce a run summary
8. The run completes

### Artifacts are the backbone

Every step writes its output to an **artifacts directory**. The path is available as `{{artifacts_dir}}` in step content and gate commands. The daemon automatically collects artifacts from completed steps and injects them into the prompt for subsequent steps.

This means:
- Step 1 writes files to its `{{artifacts_dir}}/`
- Step 2 receives the contents of Step 1's files as context in its prompt
- Step 3 receives Step 1 + Step 2 artifacts, and so on

The agent does not need to read files from previous steps — the daemon reads them and includes them in the prompt. However, `_result.md` and other artifact files are real files on disk, so gates and IF commands can reference them by path if needed.

### The `_result.md` convention

Every step **must** produce a `_result.md` file in its `{{artifacts_dir}}/`. This is the primary artifact:

- It gets a higher character budget (50,000 chars) when passed to subsequent steps
- It is displayed in the inbox for `hitl` steps
- It is the content shown in the run UI
- The daemon prepends an **automatic gate** to every step that checks the artifacts directory is non-empty — if the step produces no files at all, this gate fails

Other files saved to `{{artifacts_dir}}/` are also collected, but with a lower per-file limit (20,000 chars) and a total budget across all artifacts (120,000 chars). Binary files (images, archives, etc.) are listed but their content is not included in the prompt.

### Artifact directory layout

```
.llmflows/runs/<run_id>/artifacts/
├── 00-fetch-articles/         # Step 0 artifacts
│   ├── _result.md             # Primary output (required)
│   ├── article-1.md           # Additional files
│   ├── article-2.md
│   └── attachments/           # Published to run summary
│       └── screenshot.png
├── 01-summarize/              # Step 1 artifacts
│   └── _result.md
└── summary.md                 # Auto-generated run summary
```

Step directories are named `NN-step-name` — zero-padded position + step name lowercased with spaces replaced by hyphens (e.g. step `"Fetch articles"` at position 0 → `00-fetch-articles`).

To publish files (screenshots, images, reports) in the run summary UI, save them to `{{artifacts_dir}}/attachments/`. Images are rendered inline; other files appear as download links.

---

## Step Types

Each step has a `step_type` that controls how the daemon handles execution.

Valid step types: `"agent"`, `"code"`, `"shell"`, `"hitl"`

Any unrecognized value (including `null`, empty string, or `"default"`) is normalized to `"agent"`.

### `"agent"` (omit `step_type` or set to `"agent"`)

Runs via the **Pi** agent — llmflows' built-in tool-using agent backed by an LLM. Pi has tools for reading/writing/editing files, running shell commands, and (when enabled) web search/fetch. This is the most common step type for research, analysis, content generation, and automation tasks.

- Async: the daemon polls until the agent finishes
- After completion, gates are evaluated
- Agent alias maps to a `"pi"` alias type (configured in Settings > Agents)

**When to use:** Most steps. Any task that requires reasoning, reading files, writing output, running commands, or using tools.

### `"code"`

Runs via an **external code agent** (Cursor, Claude Code, etc.) — a CLI-based coding agent launched as a subprocess. The agent receives the rendered prompt and works in the project directory.

- Async: the daemon polls until the agent process exits
- After completion, gates are evaluated
- Agent alias maps to a `"code"` alias type (configured in Settings > Agents)

**When to use:** Steps that require deep code editing in a project — implementing features, refactoring, fixing bugs. The external agent has full access to the project workspace.

### `"shell"`

Runs the step's `content` field directly as a **shell command** (not as an agent prompt). No LLM is involved. The command runs in the space's working directory with a 600-second timeout. stdout/stderr and exit code are captured and written to `_result.md` automatically.

- **Synchronous**: the daemon blocks until the command finishes
- Space variables are injected as **environment variables** in the shell
- Template variables (`{{run.id}}`, `{{artifacts_dir}}`, etc.) are interpolated in the content before execution
- Gates are evaluated after the command completes

**When to use:** Deterministic automation steps — running builds, deployments, API calls, data processing scripts. Any step where an LLM would add no value.

**Example:**

```json
{
  "name": "build",
  "position": 2,
  "step_type": "shell",
  "content": "cd {{space.PROJECT_PATH}} && npm run build 2>&1",
  "gates": [
    {"command": "test -f {{space.PROJECT_PATH}}/dist/index.js", "message": "Build output not found."}
  ]
}
```

### `"hitl"` (human-in-the-loop)

Uses the same executor as `"agent"` (Pi agent), but after the agent finishes, instead of evaluating gates, the daemon **pauses the flow and creates an inbox item**. The user sees the agent's output (from `_result.md`) in the UI with a text input field to respond.

**The lifecycle:**

1. Agent runs the step's prompt and writes output to `_result.md`
2. Daemon marks the step as "awaiting user" (gates are **not** evaluated)
3. Step appears in the **Inbox** with the agent's output and a text input
4. User reads the output and submits a response
5. Daemon marks the step complete and advances to the next step
6. The user's response is available to all subsequent steps as context

**When to use:** When the flow needs human judgment before proceeding — choosing between approaches, approving a plan, providing input, confirming before a destructive action, visual review.

**Example:**

```json
{
  "name": "propose-approach",
  "position": 0,
  "step_type": "hitl",
  "content": "# PROPOSE APPROACHES\n\n## PURPOSE\n\nAnalyze the task and propose 2-3 implementation approaches.\n\n## WORKFLOW\n\n1. Study the codebase\n2. Identify 2-3 distinct approaches\n3. Present them clearly with pros/cons\n4. End with a question asking the user which approach to take"
}
```

**Edge cases:**
- `hitl` steps have **no gates** — the daemon skips gate evaluation entirely
- The user's response is passed as context to all subsequent steps (via the `User Responses` section in the prompt)
- The user's response is also available as a template variable: `{{steps.propose-approach.user_response}}`

---

## Gates

Gates are shell commands attached to a step that **must exit 0** before the flow can advance past that step. If any gate fails, the agent is relaunched with the failure details and must fix the problem.

### How gates work

1. After a step's agent finishes, the daemon evaluates all gates in order
2. Each gate runs as a shell command (`shell=True`) in the space's working directory
3. If **any** gate exits non-zero (or times out), the step is considered failed
4. The agent is relaunched with:
   - All the original step context
   - The gate failure details (command, message, stderr output)
   - The agent's task: fix the issues and try again
5. After the relaunched agent finishes, gates are re-evaluated
6. This loop repeats up to `max_gate_retries` times (default: 5)

### Gate structure

```json
{
  "command": "npm test -- --watchAll=false",
  "message": "All tests must pass before advancing."
}
```

- `command` — shell command that must exit 0. Supports `{{variable}}` interpolation.
- `message` — human-readable description shown to the agent on failure. Supports `{{variable}}` interpolation.

### The automatic artifact gate

The daemon **automatically prepends** a gate to every step (except `__summary__`) that checks the step's artifacts directory exists and is non-empty:

```bash
test -d "<artifacts_dir>" && test "$(ls -A "<artifacts_dir>")"
```

This means every step must produce at least one file in `{{artifacts_dir}}/`. If the agent finishes without writing any artifacts, this auto-gate fails and the agent is relaunched.

### Gate retry behavior

| `max_gate_retries` | Behavior |
|--------------------|----------|
| `5` (default) | Up to 5 retries, then run is marked `interrupted` |
| `0` or `null` | **Unlimited** retries — the agent retries forever until gates pass |
| Any positive number | That many retries |

### `allow_max` — last-resort escalation

When `allow_max` is `true` and this is the **last retry attempt**, the daemon escalates to the `"max"` agent alias tier — typically a more capable (and expensive) model. This gives the agent one final strong attempt to fix the problem.

Only useful when `max_gate_retries > 1`. Typically set on execute and test steps.

### Gate timeout

Gates have a configurable timeout (default: 60 seconds, set in system config under `daemon.gate_timeout_seconds`). If a gate command exceeds this timeout, it counts as a failure.

### Good gates vs bad gates

**Good gates** — deterministic, fast, objective:
- `npm test -- --watchAll=false` — tests pass
- `npm run build` — build succeeds
- `test -f {{artifacts_dir}}/report.md` — specific file was created
- `python -m py_compile main.py` — syntax is valid
- `ls {{artifacts_dir}}/*.png 2>/dev/null | grep -q .` — screenshots exist
- `git diff --cached --quiet || echo ok` — changes are staged

**Bad gates** — subjective, slow, unreliable:
- `curl https://api.example.com/health` — external dependency, flaky
- Complex scripts that might hang
- Anything that takes more than a few seconds

---

## IF Conditions

IFs are shell commands that control whether a step is **entered at all**. They are evaluated before the step launches. If **any** IF command exits non-zero, the step is **skipped** and the daemon advances to the next step.

### How IFs work

1. Before launching a step, the daemon evaluates all `ifs` entries
2. **ALL** commands must exit 0 for the step to run
3. If any IF exits non-zero (or times out/errors), the step is **skipped entirely**
4. The daemon moves to the next step and evaluates its IFs
5. If all remaining steps are skipped, the `__summary__` step runs

### IF structure

```json
{
  "command": "test -f package.json",
  "message": "Node.js project exists"
}
```

- `command` — shell command. Exit 0 = condition met. Non-zero = skip step. Supports `{{variable}}` interpolation.
- `message` — human-readable description (for logging/debugging).

### IF vs Gates comparison

| Aspect | IF | Gate |
|--------|-----|------|
| **When** | Before step enters | After step completes |
| **Purpose** | Should this step run? | Did this step succeed? |
| **On failure** | Step is skipped silently | Agent is relaunched to fix |
| **Retries** | No | Yes (`max_gate_retries`) |
| **Agent sees it** | No | Yes (failure details in prompt) |

### IF edge cases

- Empty `command` entries are skipped (treated as pass)
- Timeout or exceptions count as failure (step is skipped)
- IFs have a **narrower set of template variables** than step content — see the Template Variables section for details
- IFs use the same timeout as gates (`daemon.gate_timeout_seconds`)

### Example: conditional language-specific steps

```json
[
  {
    "name": "lint-python",
    "position": 2,
    "step_type": "agent",
    "content": "...",
    "ifs": [
      {"command": "test -f requirements.txt || test -f pyproject.toml", "message": "Python project"}
    ]
  },
  {
    "name": "lint-js",
    "position": 3,
    "step_type": "agent",
    "content": "...",
    "ifs": [
      {"command": "test -f package.json", "message": "Node project"},
      {"command": "grep -q eslint package.json", "message": "ESLint configured"}
    ]
  }
]
```

---

## Template Variables

Step content, gate commands, gate messages, and IF commands support `{{variable}}` interpolation. The pattern matches `{{key}}` where key can contain letters, digits, `_`, `.`, and `-`.

| Variable | Step content | Gates | IFs |
|----------|:---:|:---:|:---:|
| `{{run.id}}` — current run ID | Yes | Yes | Yes |
| `{{flow.name}}` — current flow name | Yes | Yes | Yes |
| `{{artifacts_dir}}` — absolute path to this step's artifact output directory | Yes | Yes | **No** |
| `{{space.KEY}}` — space variable (set via Settings or CLI) | Yes | Yes | Yes |
| `{{steps.STEP_NAME.user_response}}` — user's response from a completed `hitl` step | Yes | Yes | **No** |

IFs are evaluated **before** the step launches, so `{{artifacts_dir}}` and `{{steps.*.user_response}}` are not yet available.

### Space variables

Space variables are key-value pairs configured by the user (in Settings or via CLI) and available to all flows in the space. Reference them as `{{space.KEY_NAME}}` in step content, gate commands, and gate messages.

For `shell` steps, space variables are also injected as **environment variables**, so `$PROJECT_PATH` works directly in shell commands.

### What the agent automatically receives

The agent's prompt is built by the system and automatically includes (flow authors do not need to set these up):
- **Previous step artifacts** — `_result.md` and other files from all completed steps
- **Gate failure details** — on retry, the agent sees which gates failed, with stderr output
- **User responses** — all responses from completed `hitl` steps
- **Space variables** — listed as available environment variables
- **Skills** — any skills attached to the step

---

## Flow Requirements

Flows can declare requirements — tools and variables they need to function. Requirements are **validated before running** (warnings are shown in the UI) but are **not enforced** at runtime.

```json
{
  "name": "ai-news",
  "description": "Fetch the latest AI news.",
  "requirements": {
    "tools": ["web_search"],
    "variables": ["API_KEY"]
  },
  "steps": [...]
}
```

### `requirements.tools`

A list of tool names that must be enabled in system config (Settings > Tools). If a required tool is not enabled, a `missing_tool` warning is shown in the UI. The run modal treats this as a **blocking warning** — the user must enable the tool before starting.

Currently supported tools: `"web_search"` (gives Pi steps access to `web_search` and `web_fetch` tools).

### `requirements.variables`

A list of space variable names that must be set (via `llmflows space var set KEY VALUE`). If a variable is missing or empty, a `missing_variable` warning is shown. Also treated as blocking in the run modal.

Use this to declare dependencies on configuration that the user must provide.

---

## Step Fields Reference

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `name` | string | **required** | Step identifier. Used in artifact directory names and template variables. |
| `position` | integer | **required** | Sequential index starting at 0. Must be sequential. |
| `content` | string | `""` | Markdown prompt (for agent steps) or shell command (for `shell` steps). |
| `step_type` | string | `"agent"` | One of: `"agent"`, `"code"`, `"shell"`, `"hitl"`. Omit for agent. |
| `agent_alias` | string | `"normal"` | Which agent tier to use. Common values: `"mini"`, `"normal"`, `"max"`. |
| `allow_max` | boolean | `false` | On the last gate retry, escalate to the `"max"` agent alias. |
| `max_gate_retries` | integer | `5` | Max retry attempts on gate failure. `0` = unlimited. |
| `gates` | array | `[]` | Shell commands that must pass to advance. See Gates section. |
| `ifs` | array | `[]` | Shell commands that must pass to enter the step. See IF section. |
| `skills` | array | `[]` | Skill identifiers to load for this step. |

### Agent aliases

Agent aliases map to agent configurations (model + provider) in Settings > Agents. Each alias has a **type** (`"pi"` or `"code"`) and a **name** (tier).

| Alias name | Intended use |
|------------|-------------|
| `"mini"` | Trivial steps: commits, file moves, simple formatting |
| `"normal"` | Standard steps: most research, analysis, implementation |
| `"max"` | Complex reasoning: architecture, multi-file refactors, difficult debugging |

The alias type is determined by step_type:
- `"agent"` and `"hitl"` → `"pi"` alias type
- `"code"` → `"code"` alias type
- `"shell"` → no alias (no LLM involved)

---

## Step Content Format

Each step's `content` is a markdown prompt given to the agent. Use clear sections:

| Section | Required | Purpose |
|---------|----------|---------|
| `# TITLE` | Yes | Step name in uppercase |
| `## PURPOSE` | Yes | One-sentence goal — what this step must accomplish |
| `## WORKFLOW` | Yes | Numbered action list — concrete steps to follow |
| `## RULES` | No | Output format, quality constraints |
| `## PERMITTED` | No | Explicitly allowed actions (useful to override restrictions) |
| `## FORBIDDEN` | No | Hard constraints — things the agent must never do |


---

## Flow JSON Format

The export/import format. One file can contain multiple flows.

```json
{
  "version": 1,
  "flows": [
    {
      "name": "my-flow",
      "description": "What this flow does.",
      "requirements": {
        "tools": ["web_search"],
        "variables": ["API_KEY"]
      },
      "steps": [
        {
          "name": "step-name",
          "position": 0,
          "step_type": "agent",
          "content": "# STEP TITLE\n\n## PURPOSE\n\n...\n\n## WORKFLOW\n\n1. ...",
          "gates": [
            {"command": "test -f {{artifacts_dir}}/output.md", "message": "Output file must exist."}
          ],
          "ifs": [],
          "agent_alias": "normal",
          "allow_max": false,
          "max_gate_retries": 5,
          "skills": []
        }
      ]
    }
  ]
}
```

Fields at their default values can be omitted — see the Step Fields Reference for defaults.

---

## Best Practices

### Design smaller steps with artifact validation

Break work into small steps where each produces a concrete, verifiable artifact. Then use gates to validate that artifact before proceeding.

**Bad** — one big step:
```
Step 1: Research the topic, write an outline, write the full article, and format it
```

**Good** — smaller steps with gates:
```
Step 0: Research → saves research notes to artifacts → gate: notes file exists
Step 1: Outline → reads research from context, writes outline → gate: outline file exists
Step 2: Write → reads outline from context, writes article → gate: article file exists
Step 3: Format → reads article from context, formats and validates → gate: final file passes validation
```

Each step has a single responsibility, its output can be validated, and if something goes wrong the agent only needs to redo that one step.

### Constraint progression

Tighten permissions as the flow advances:

- **Early steps** (research/plan): `FORBIDDEN: No code changes, no git operations`
- **Execute steps**: `FORBIDDEN: No git operations, no scope expansion`
- **Commit/final steps**: `FORBIDDEN: Do not push to remote`

### Keep steps self-contained

The agent only sees one step at a time. Each step must include everything the agent needs:
- What to do (workflow)
- Where to save output (artifacts dir)
- What constraints to follow (rules/forbidden)
- Any file paths or configuration needed

Don't assume the agent remembers instructions from previous steps — it doesn't.

### Tell subsequent steps what to expect

When a step consumes output from a previous step, describe the format explicitly. The agent receives previous artifacts as context but doesn't know the structure unless you say so.

**Bad:** "Read the data from the previous step."
**Good:** "The articles from the previous step are in your context. Each is a markdown file with: headline, author, date, URL, and full text."

---

## Reference Examples

### Simple research flow (2 steps)

```json
{
  "version": 1,
  "flows": [
    {
      "name": "ai-news",
      "description": "Fetch the latest AI news from TechCrunch, store each article, then summarize.",
      "requirements": {
        "tools": ["web_search"]
      },
      "steps": [
        {
          "name": "Fetch articles",
          "position": 0,
          "step_type": "agent",
          "content": "# FETCH ARTICLES\n\n## PURPOSE\n\nFetch the 5 most recent articles and save each as a separate artifact.\n\n## WORKFLOW\n\n1. Use `web_fetch` to load the target URL\n2. Extract the 5 most recent article links\n3. For each, fetch the full article and extract content\n4. Save each article to `{{artifacts_dir}}/article-N.md`\n\n## RULES\n\n- Save exactly 5 articles, one per file\n- Preserve original content faithfully",
          "gates": [
            {
              "command": "test -f {{artifacts_dir}}/article-1.md && test -f {{artifacts_dir}}/article-5.md",
              "message": "Not all 5 article files were saved."
            }
          ]
        },
        {
          "name": "Summarize",
          "position": 1,
          "step_type": "agent",
          "content": "# SUMMARIZE\n\n## PURPOSE\n\nProduce a concise summary of all articles from the previous step.\n\n## WORKFLOW\n\n1. Read the articles from context (they are provided automatically)\n2. Write a 2-3 sentence summary for each\n3. Save to `{{artifacts_dir}}/_result.md`\n\n## RULES\n\n- Use article content from context, do not fetch anything\n- Preserve original headlines exactly"
        }
      ]
    }
  ]
}
```

### Flow with hitl approval

```json
{
  "name": "reviewed-implementation",
  "description": "Propose approaches, get user approval, then implement.",
  "steps": [
    {
      "name": "propose",
      "position": 0,
      "step_type": "hitl",
      "content": "# PROPOSE\n\n## PURPOSE\n\nAnalyze the task and propose 2-3 approaches.\n\n## WORKFLOW\n\n1. Study the codebase\n2. Propose 2-3 approaches with pros/cons\n3. End with: \"Which approach should I implement?\""
    },
    {
      "name": "implement",
      "position": 1,
      "step_type": "agent",
      "agent_alias": "max",
      "content": "# IMPLEMENT\n\n## PURPOSE\n\nImplement the approach the user chose.\n\n## WORKFLOW\n\n1. Read the user's response from context — it specifies which approach\n2. Implement that approach\n3. Write a summary of changes to `{{artifacts_dir}}/_result.md`",
      "gates": [
        {"command": "npm test -- --watchAll=false", "message": "Tests must pass."}
      ],
      "allow_max": true,
      "max_gate_retries": 3
    }
  ]
}
```

### Flow with conditional steps

```json
{
  "name": "polyglot-lint",
  "description": "Lint whatever languages are present in the project.",
  "steps": [
    {
      "name": "lint-python",
      "position": 0,
      "step_type": "shell",
      "content": "cd {{space.PROJECT_PATH}} && python -m ruff check . 2>&1",
      "ifs": [
        {"command": "test -f {{space.PROJECT_PATH}}/pyproject.toml", "message": "Python project exists"}
      ]
    },
    {
      "name": "lint-js",
      "position": 1,
      "step_type": "shell",
      "content": "cd {{space.PROJECT_PATH}} && npx eslint . 2>&1",
      "ifs": [
        {"command": "test -f {{space.PROJECT_PATH}}/package.json", "message": "Node project exists"},
        {"command": "grep -q eslint {{space.PROJECT_PATH}}/package.json", "message": "ESLint configured"}
      ]
    }
  ]
}
```
