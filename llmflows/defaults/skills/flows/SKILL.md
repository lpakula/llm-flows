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
7. After the last step, the run completes — the last step's `_result.md` becomes the run summary
8. If the run fails (timeout, gate failure, etc.), a `__summarizer__` step runs to produce an error diagnosis

### Artifacts are the backbone

Every step writes its output to an **artifacts directory**. The path is available as `{{run.dir}}` in step content and gate commands. The daemon automatically collects artifacts from completed steps and injects them into the prompt for subsequent steps.

This means:
- Step 1 writes files to its `{{run.dir}}/`
- Step 2 receives the contents of Step 1's files as context in its prompt
- Step 3 receives Step 1 + Step 2 artifacts, and so on

The agent does not need to read files from previous steps — the daemon reads them and includes them in the prompt. However, `_result.md` and other artifact files are real files on disk, so gates and IF commands can reference them by path if needed.

### The `_result.md` convention

Every step **must** produce a `_result.md` file in its `{{run.dir}}/`. This is the primary artifact:

- It gets a higher character budget (50,000 chars) when passed to subsequent steps
- It is displayed in the inbox for `hitl` steps
- It is the content shown in the run UI
- The daemon prepends an **automatic gate** to every step that checks the artifacts directory is non-empty — if the step produces no files at all, this gate fails

Other files saved to `{{run.dir}}/` are also collected, but with a lower per-file limit (20,000 chars) and a total budget across all artifacts (120,000 chars). Binary files (images, archives, etc.) are listed but their content is not included in the prompt.

### Artifact directory layout

```
.llmflows/<flow-name>/                # Persistent flow directory ({{flow.dir}})
├── runs/<run_id>/artifacts/          # Per-run artifacts ({{run.dir}})
│   ├── 00-fetch-articles/            # Step 0 artifacts
│   │   ├── _result.md                # Primary output (required)
│   │   ├── article-1.md              # Additional files
│   │   ├── article-2.md
│   │   └── attachments/              # Published to run summary
│   │       └── screenshot.png
│   ├── 01-summarize/                 # Step 1 artifacts
│   │   └── _result.md
│   └── summary.md                    # Auto-generated run summary
└── ...                               # Any persistent cross-run data
```

Step directories are named `NN-step-name` — zero-padded position + step name lowercased with spaces replaced by hyphens (e.g. step `"Fetch articles"` at position 0 → `00-fetch-articles`).

To publish files (screenshots, images, reports) in the run summary UI, save them to `{{run.dir}}/attachments/`. Images are rendered inline; other files appear as download links.

---

## Step Types

Each step has a `step_type` that controls how the daemon handles execution.

Valid step types: `"agent"`, `"code"`, `"hitl"`

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

The daemon **automatically prepends** a gate to every step that checks the step's artifacts directory exists and is non-empty:

```bash
test -d "<run.dir>" && test "$(ls -A "<run.dir>")"
```

This means every step must produce at least one file in `{{run.dir}}/`. If the agent finishes without writing any artifacts, this auto-gate fails and the agent is relaunched.

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
- `test -f {{run.dir}}/report.md` — specific file was created
- `python -m py_compile main.py` — syntax is valid
- `ls {{run.dir}}/*.png 2>/dev/null | grep -q .` — screenshots exist
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
5. If all remaining steps are skipped, the run completes

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
| `{{run.dir}}` — absolute path to this step's artifact output directory | Yes | Yes | **No** |
| `{{flow.dir}}` — persistent flow directory (`.llmflows/<flow>/`), shared across runs | Yes | Yes | Yes |
| `{{space.KEY}}` — space variable (set via Settings or CLI) | Yes | Yes | Yes |
| `{{steps.STEP_NAME.user_response}}` — user's response from a completed `hitl` step | Yes | Yes | **No** |

IFs are evaluated **before** the step launches, so `{{run.dir}}` and `{{steps.*.user_response}}` are not yet available.

### Space variables

Space variables are key-value pairs configured by the user (in Settings or via CLI) and available to all flows in the space. Reference them as `{{space.KEY_NAME}}` in step content, gate commands, and gate messages.

### What the agent automatically receives

The agent's prompt is built by the system and automatically includes (flow authors do not need to set these up):
- **Previous step artifacts** — `_result.md` and other files from all completed steps
- **Gate failure details** — on retry, the agent sees which gates failed, with stderr output
- **User responses** — all responses from completed `hitl` steps
- **Space variables** — listed as available environment variables
- **Skills** — any skills attached to the step

---

## Step Tools

Tools are declared **per step** via the `tools` field. Each step declares which optional tools it needs. The daemon starts/stops tool services (like the browser) based on step transitions — if consecutive steps share a tool, the session persists; when a step without the tool runs, the service is cleaned up.

Pi always has `read`, `write`, `edit`, and `shell` tools available — these do not need to be declared. The following optional tools can be declared per step:

- `"web_search"` — gives the step access to `web_search` and `web_fetch` tools for searching the web and fetching page content.
- `"browser"` — gives the step access to `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_fill`, and `browser_screenshot` tools for controlling a real Chrome browser. The browser session persists across consecutive steps that declare `"browser"`, so login state, cookies, and page context carry over. A persistent profile in `~/.llmflows/browser-profile/` preserves login sessions across runs.

If any step declares a tool that is not enabled in Settings > Tools, a `missing_tool` warning is shown in the UI.

```json
{
  "name": "step-with-browser",
  "position": 0,
  "content": "...",
  "tools": ["browser"]
}
```

## Flow Variables

Flows can declare variables they need to function. Variables are key-value pairs set on the flow page (or via `llmflows flow var set FLOW KEY VALUE`) and available in step content, gate commands, and IF commands.

Use variables for any configuration the user must provide: API keys, URLs, credentials, project paths, etc. If a variable has no value, the UI shows a `missing_variable` warning and blocks the run until it is filled.

### Setting variables

Variables are set per flow in the UI (flow page > Variables section) or via CLI:

```bash
llmflows flow var set my-flow TARGET_URL "https://example.com"
llmflows flow var set my-flow API_KEY "sk-..."
```

### Using variables in step content

Reference variables as `{{flow.KEY}}` or `{{space.KEY}}` in step content, gates, and IFs:

```markdown
## WORKFLOW

1. Use `browser_navigate` to go to {{flow.TARGET_URL}}
2. Use `browser_fill` to enter {{flow.USERNAME}} and {{flow.PASSWORD}}
```

### Variables in flow JSON

When exporting/importing flows, variables appear at the flow level:

```json
{
  "name": "my-flow",
  "variables": {
    "TARGET_URL": "",
    "USERNAME": "",
    "PASSWORD": ""
  },
  "steps": [...]
}
```

Variable values are intentionally left empty in exports — the user fills them in after importing. This keeps secrets out of flow JSON files.

---

## Step Fields Reference

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `name` | string | **required** | Step identifier. Used in artifact directory names and template variables. |
| `position` | integer | **required** | Sequential index starting at 0. Must be sequential. |
| `content` | string | `""` | Markdown prompt for the step. |
| `step_type` | string | `"agent"` | One of: `"agent"`, `"code"`, `"hitl"`. Omit for agent. |
| `agent_alias` | string | `"normal"` | Which agent tier to use. Common values: `"mini"`, `"normal"`, `"max"`. |
| `allow_max` | boolean | `false` | On the last gate retry, escalate to the `"max"` agent alias. |
| `max_gate_retries` | integer | `5` | Max retry attempts on gate failure. `0` = unlimited. |
| `gates` | array | `[]` | Shell commands that must pass to advance. See Gates section. |
| `ifs` | array | `[]` | Shell commands that must pass to enter the step. See IF section. |
| `skills` | array | `[]` | Skill identifiers to load for this step. |
| `tools` | array | `[]` | Optional tool names for this step: `"browser"`, `"web_search"`. |

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
      "steps": [
        {
          "name": "step-name",
          "position": 0,
          "step_type": "agent",
          "content": "# STEP TITLE\n\n## PURPOSE\n\n...\n\n## WORKFLOW\n\n1. ...",
          "gates": [
            {"command": "test -f {{run.dir}}/output.md", "message": "Output file must exist."}
          ],
          "ifs": [],
          "agent_alias": "normal",
          "allow_max": false,
          "max_gate_retries": 5,
          "skills": [],
          "tools": []
        }
      ]
    }
  ]
}
```

Fields at their default values can be omitted — see the Step Fields Reference for defaults.

---

## Browser Automation

Steps can control a real Chrome browser by declaring `"browser"` in their `tools` array. The browser session is managed by the daemon and persists across **consecutive steps** that declare `"browser"` — login state, cookies, and open pages carry over, including across `hitl` pauses. When a step without `"browser"` runs, the daemon cleans up the browser session.

The browser uses the system Google Chrome (not Playwright's bundled Chromium) with a persistent profile stored in `~/.llmflows/browser-profile/`. This means:
- **Login sessions persist across runs** — log in to Google/GitHub/etc. once, and future runs reuse the session via saved cookies
- **Downloads go to the step's artifacts directory** — any file downloaded by the browser during a step is automatically captured as a step artifact
- **Google login works** — system Chrome avoids the automation fingerprints that cause Google to block sign-in

### How it works

1. When a step with `"browser"` in its `tools` is launched, the daemon starts a Chrome browser server (or reuses an existing one for the run)
2. The step's agent receives browser tools that connect to the running browser
3. The agent interacts with pages using a **snapshot-and-ref model**: `browser_snapshot` returns a text representation of the page where interactive elements are tagged with `[ref=N]`, and the agent targets elements by ref number
4. When the next step does not declare `"browser"`, the daemon kills the browser. When the run completes (or fails/times out), the daemon also kills the browser as a safety net

### Available browser tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `browser_navigate` | `url: string` | Navigate to a URL. Returns page snapshot with refs. |
| `browser_snapshot` | *(none)* | Get current page structure with `[ref=N]` tags for interactive elements. |
| `browser_click` | `ref: number` | Click an element by its ref number. Returns fresh snapshot. |
| `browser_fill` | `ref: number, value: string` | Fill an input/textarea by ref. Clears existing content first. Returns fresh snapshot. |
| `browser_screenshot` | `filename?: string` | Save a screenshot to the artifacts directory. Returns the file path. |

### The snapshot-and-ref model

Instead of CSS selectors, the agent sees a clean text representation of interactive elements:

```
Page: https://example.com/login

heading "Sign In"
  textbox "Email" [ref=1]
  textbox "Password" [ref=2]
  button "Sign In" [ref=3]
  link "Forgot password?" [ref=4]
```

The agent then uses ref numbers to interact: `browser_fill(ref=1, value="user@example.com")`, `browser_click(ref=3)`. Refs are rebuilt on each snapshot/navigate/click/fill call, so they always reflect the current page state.

### Writing browser steps

- **Only the first browser step needs `browser_navigate`** — subsequent consecutive browser steps inherit the exact browser state (URL, page content, open tabs, cookies, localStorage) from the previous step. If step 1 navigates to a page, step 2 can immediately call `browser_snapshot` to see that same page without re-navigating
- **Use `browser_snapshot`** at the start of a continuation step to see where the browser is, then interact from there. No need to re-navigate or re-login
- **Use `browser_screenshot`** to capture visual confirmation and save to artifacts (useful for gates and for `hitl` steps where the user needs to see the page)
- **Browser state persists across consecutive browser steps** — if step 1 logs in and step 2 also declares `"browser"`, step 2 sees the authenticated session with the same page still open. The daemon manages one browser server per run and reuses it across consecutive steps that declare `"browser"`. If a step without `"browser"` runs in between, the session is cleaned up
- **`hitl` steps work naturally with browser** — the browser stays alive while waiting for user input, as long as the `hitl` step declares `"browser"` in its tools. This is a key design pattern: use one step to navigate to a page, a `hitl` step (with browser) to ask the user for input (e.g., MFA code, CAPTCHA, manual approval), then continue in a subsequent step with the same browser session. The page the user sees is the same page the previous step left open
- **Split browser workflows across steps** — don't try to do everything in one step. Use separate steps for navigation/login, user interaction (`hitl`), and the actual task. Make sure each step that needs the browser declares `"browser"` in its `tools`. Each step picks up exactly where the last one left off

### Browser step tools

```json
{
  "name": "login",
  "position": 0,
  "tools": ["browser"],
  "content": "..."
}
```

The `"browser"` tool must be enabled in Settings > Tools. Space variables are available in step content via `{{space.USERNAME}}`.

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
      "steps": [
        {
          "name": "Fetch articles",
          "position": 0,
          "step_type": "agent",
          "tools": ["web_search"],
          "content": "# FETCH ARTICLES\n\n## PURPOSE\n\nFetch the 5 most recent articles and save each as a separate artifact.\n\n## WORKFLOW\n\n1. Use `web_fetch` to load the target URL\n2. Extract the 5 most recent article links\n3. For each, fetch the full article and extract content\n4. Save each article to `{{run.dir}}/article-N.md`\n\n## RULES\n\n- Save exactly 5 articles, one per file\n- Preserve original content faithfully",
          "gates": [
            {
              "command": "test -f {{run.dir}}/article-1.md && test -f {{run.dir}}/article-5.md",
              "message": "Not all 5 article files were saved."
            }
          ]
        },
        {
          "name": "Summarize",
          "position": 1,
          "step_type": "agent",
          "content": "# SUMMARIZE\n\n## PURPOSE\n\nProduce a concise summary of all articles from the previous step.\n\n## WORKFLOW\n\n1. Read the articles from context (they are provided automatically)\n2. Write a 2-3 sentence summary for each\n3. Save to `{{run.dir}}/_result.md`\n\n## RULES\n\n- Use article content from context, do not fetch anything\n- Preserve original headlines exactly"
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
      "content": "# IMPLEMENT\n\n## PURPOSE\n\nImplement the approach the user chose.\n\n## WORKFLOW\n\n1. Read the user's response from context — it specifies which approach\n2. Implement that approach\n3. Write a summary of changes to `{{run.dir}}/_result.md`",
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
      "agent_alias": "mini",
      "content": "# LINT PYTHON\n\n## PURPOSE\n\nRun the Python linter and capture results.\n\n## WORKFLOW\n\n1. Run `cd {{space.PROJECT_PATH}} && python -m ruff check .`\n2. Save the full output to `{{run.dir}}/_result.md`\n\n## FORBIDDEN\n\n- Do not fix any issues, only report them",
      "ifs": [
        {"command": "test -f {{space.PROJECT_PATH}}/pyproject.toml", "message": "Python project exists"}
      ]
    },
    {
      "name": "lint-js",
      "position": 1,
      "agent_alias": "mini",
      "content": "# LINT JAVASCRIPT\n\n## PURPOSE\n\nRun the JavaScript linter and capture results.\n\n## WORKFLOW\n\n1. Run `cd {{space.PROJECT_PATH}} && npx eslint .`\n2. Save the full output to `{{run.dir}}/_result.md`\n\n## FORBIDDEN\n\n- Do not fix any issues, only report them",
      "ifs": [
        {"command": "test -f {{space.PROJECT_PATH}}/package.json", "message": "Node project exists"},
        {"command": "grep -q eslint {{space.PROJECT_PATH}}/package.json", "message": "ESLint configured"}
      ]
    }
  ]
}
```

### Flow with browser automation and hitl

```json
{
  "name": "login-and-act",
  "description": "Log into a website with MFA, then perform an action in the browser.",
  "steps": [
    {
      "name": "login",
      "position": 0,
      "tools": ["browser"],
      "content": "# LOGIN\n\n## PURPOSE\n\nNavigate to the login page and enter credentials.\n\n## WORKFLOW\n\n1. Use `browser_navigate` to go to {{space.TARGET_URL}}\n2. Use the snapshot to find the username and password fields\n3. Use `browser_fill` to enter {{space.USERNAME}} and {{space.PASSWORD}}\n4. Use `browser_click` to submit the form\n5. Take a `browser_screenshot` and save to `{{run.dir}}/login.png`\n6. Write the current page state to `{{run.dir}}/_result.md`",
      "gates": [
        {"command": "test -f {{run.dir}}/login.png", "message": "Login screenshot must exist."}
      ]
    },
    {
      "name": "get-mfa-code",
      "position": 1,
      "step_type": "hitl",
      "tools": ["browser"],
      "content": "# MFA CODE REQUIRED\n\n## PURPOSE\n\nShow the user the current browser state and ask for the MFA code.\n\n## WORKFLOW\n\n1. Take a `browser_screenshot` and save to `{{run.dir}}/mfa-prompt.png`\n2. Use `browser_snapshot` to describe the current page\n3. Write to `{{run.dir}}/_result.md`: explain that credentials were entered and the site is asking for an MFA code, then ask the user to provide it"
    },
    {
      "name": "submit-mfa",
      "position": 2,
      "tools": ["browser"],
      "content": "# SUBMIT MFA\n\n## PURPOSE\n\nEnter the MFA code provided by the user and complete login.\n\n## WORKFLOW\n\n1. The user's MFA code is: {{steps.get-mfa-code.user_response}}\n2. Use `browser_snapshot` to find the MFA input field\n3. Use `browser_fill` to enter the code\n4. Use `browser_click` to submit\n5. Take a `browser_screenshot` to confirm login succeeded\n6. Save confirmation to `{{run.dir}}/_result.md`",
      "gates": [
        {"command": "test -f {{run.dir}}/screenshot.png", "message": "Confirmation screenshot must exist."}
      ]
    },
    {
      "name": "perform-action",
      "position": 3,
      "tools": ["browser"],
      "content": "# PERFORM ACTION\n\n## PURPOSE\n\nExecute the target action in the authenticated browser session.\n\n## WORKFLOW\n\n1. Use `browser_navigate` or `browser_snapshot` to find the target page/form\n2. Fill in any required fields and submit\n3. Take a `browser_screenshot` to confirm the action\n4. Write a summary of what was done to `{{run.dir}}/_result.md`"
    }
  ]
}
```
