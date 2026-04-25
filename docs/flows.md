# Flow Authoring

A **flow** is an ordered list of **steps** that llm-flows executes one by one. Each step runs as a separate AI agent process. Steps produce output files (artifacts) that are automatically passed as context to the next step. Steps can have **gates** (checks that must pass) and **IFs** (conditions that decide whether to run).

---

## How a flow runs

1. The daemon picks the first step and evaluates its **IF conditions**
2. If IFs pass (or there are none), the step is launched
3. The agent runs the step's instructions and produces artifacts
4. The daemon evaluates **gates** — shell commands that must exit 0
5. If all gates pass, the daemon advances to the next step
6. If a gate fails, the agent is relaunched with failure details to fix the problem
7. After the last step, a summary is automatically generated
8. The run completes and appears in the Inbox

---

## Step types

Each step has a `step_type` that controls how it executes.

### `"agent"` (default)

Runs via **Pi** — llm-flows' built-in AI agent. Pi can read/write files, run shell commands, search the web, and control a browser. This is the most common step type.

**When to use:** Research, analysis, content generation, web scraping, automation — anything that requires reasoning.

### `"code"`

Runs via an **external coding agent** (Cursor CLI, Claude Code, etc.). The agent receives the prompt and works directly in the project directory with full filesystem access.

**When to use:** Implementing features, refactoring, fixing bugs — tasks that require deep code editing.

### `"hitl"` (human-in-the-loop)

Same as `"agent"`, but after the agent finishes, the flow **pauses** and creates an inbox item. The user sees the agent's output and responds. The flow then continues with the user's response available to all subsequent steps.

**When to use:** Approvals, MFA codes, decision points, human review.

---

## Gates

Gates are shell commands attached to a step that **must exit 0** before the flow advances. If a gate fails, the agent is relaunched with the failure details.

```json
{
  "command": "npm test -- --watchAll=false",
  "message": "All tests must pass before advancing."
}
```

- `command` — shell command. Supports `{{variable}}` interpolation.
- `message` — shown to the agent on failure so it knows what to fix.

### How gates work

1. Agent finishes → daemon runs all gates in order
2. If any gate fails → agent is relaunched with failure context
3. Agent tries again → gates are re-evaluated
4. Repeats up to `max_gate_retries` times (default: 5)

### Automatic artifact gate

Every step must produce a result artifact (`_result.md`) for the flow to continue — subsequent steps depend on it for context. A built-in gate enforces this: if the step finishes without producing artifacts, the gate fails and the agent retries automatically.

### `allow_max` — last-resort escalation

When `allow_max` is `true` and this is the last retry, the daemon switches to the `"max"` agent tier (a more powerful model) for one final attempt.

### One command per gate

Each gate must be exactly **one** check. Never chain multiple checks with `&&` — use separate gates instead. This gives the agent a precise failure message for the exact check that failed.

### Good gates vs bad gates

**Good** — deterministic, fast, single-command:
- `npm test` — tests pass
- `npm run build` — build succeeds
- `test -f {{run.dir}}/report.md` — expected file exists
- `python -m py_compile main.py` — valid syntax
- `command -v ffmpeg >/dev/null 2>&1` — tool is installed

**Bad** — flaky, slow, external, or compound:
- `curl https://api.example.com/health` — depends on external service
- `command -v foo && test -f bar && python -c 'import baz'` — multiple checks in one gate
- Complex scripts that might hang

---

## IF conditions

IFs are shell commands evaluated **before** a step runs. If any IF fails, the step is **skipped entirely** — the daemon moves to the next step.

```json
{
  "command": "test -f package.json",
  "message": "Node.js project exists"
}
```

### IFs vs Gates

| | IF | Gate |
|---|---|---|
| **When** | Before step runs | After step completes |
| **Purpose** | Should this step run? | Did this step succeed? |
| **On failure** | Step is skipped | Agent retries |

---

## Template variables

Step content, gate commands, and IF commands support `{{variable}}` interpolation.

| Variable | Description |
|----------|-------------|
| `{{run.id}}` | Current run ID |
| `{{flow.name}}` | Current flow name |
| `{{run.dir}}` | Absolute path to this step's output directory |
| `{{flow.dir}}` | Persistent flow directory, shared across runs |
| `{{space.KEY}}` | Space variable set via Settings or CLI |
| `{{steps.STEP_NAME.user_response}}` | User's response from a completed `hitl` step |

Note: `{{run.dir}}` and `{{steps.*.user_response}}` are not available in IFs (they're evaluated before the step starts).

---

## Artifacts

Every step writes output to an **artifacts directory** (`{{run.dir}}`). The primary output is `_result.md` — every step must produce this file.

Artifacts from completed steps are automatically injected into the prompt for subsequent steps. The agent doesn't need to read files from previous steps — the daemon handles it.

To publish files (screenshots, images) in the run summary, save them to `{{run.dir}}/attachments/`.

---

## Step connectors

Connectors are declared **per step** via the `connectors` field. The daemon starts/stops connector services based on step transitions — consecutive steps sharing a connector keep the session alive.

```json
{
  "name": "fetch-data",
  "position": 0,
  "connectors": ["web_search"],
  "content": "..."
}
```

### Built-in connectors

- `"web_search"` — web search and page fetching
- `"browser"` — Chromium browser automation (navigate, click, fill, screenshot)

Any connector installed from the catalog or added as a custom MCP server can also be attached to a step — for example, `"notion"`, `"github"`, or `"slack_mcp"`. See **[Connectors](connectors.md)** for the full list.

### Variables

Space variables set via **Settings > Variables** or `llmflows space var set KEY VALUE`. Available as `{{space.KEY}}` in step content.

---

## Step content format

Each step's `content` is a plain markdown prompt — there is no special structure or required sections. Write it however makes sense for the task.

---

## Step fields reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | **required** | Step identifier |
| `position` | integer | **required** | Sequential index starting at 0 |
| `content` | string | `""` | Markdown prompt |
| `step_type` | string | `"agent"` | `"agent"`, `"code"`, or `"hitl"` |
| `agent_alias` | string | `"normal"` | Agent tier: `"mini"`, `"normal"`, or `"max"` |
| `allow_max` | boolean | `false` | Escalate to `"max"` on last gate retry |
| `max_gate_retries` | integer | `5` | Max retries on gate failure. `0` = unlimited |
| `gates` | array | `[]` | Shell commands that must pass |
| `ifs` | array | `[]` | Conditions that must pass to enter the step |
| `skills` | array | `[]` | Skill identifiers to load |
| `connectors` | array | `[]` | Connector IDs: `"browser"`, `"web_search"`, or any installed connector |

---

## Flow JSON format

The export/import format. Fields at their default values can be omitted.

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
          "agent_alias": "normal",
          "content": "# STEP TITLE\n\n## PURPOSE\n\n...\n\n## WORKFLOW\n\n1. ...",
          "gates": [],
          "ifs": [],
          "connectors": []
        }
      ]
    }
  ]
}
```

---

## Browser automation

Declare `"browser"` in a step's `connectors` array to give that step control of a real Chromium browser. The browser persists across consecutive steps that declare `"browser"` — login state, cookies, and pages carry over.

### Browser tools

| Tool | Description |
|------|-------------|
| `browser_navigate` | Go to a URL, returns page snapshot |
| `browser_snapshot` | Get current page structure with `[ref=N]` tags |
| `browser_click` | Click an element by ref number |
| `browser_fill` | Fill an input field by ref |
| `browser_screenshot` | Save a screenshot to artifacts |

The agent interacts using a **snapshot-and-ref model**: `browser_snapshot` returns a text representation where interactive elements have `[ref=N]` tags. The agent targets elements by ref number.

---

## Best practices

**Break work into small steps.** Each step should have one clear job. This makes flows more reliable — if something fails, only that step retries.

**Use gates to validate output.** Don't trust the agent to self-validate. Add gates that check for expected files, passing tests, or valid syntax.

**Keep steps self-contained.** The agent only sees one step at a time. Include everything it needs in the step content — don't assume it remembers previous steps.

**Tell steps what to expect from previous steps.** The agent receives artifacts from prior steps as context, but describe the format explicitly: *"The articles from the previous step are in your context. Each has a headline, author, date, and full text."*

**Tighten constraints as the flow progresses.** Early steps (research): forbid code changes. Execute steps: forbid git operations. Final steps: forbid pushing to remote.

---

## Example flows

### 1. Web research and summarize

A simple 2-step flow that fetches news articles and produces a summary. Uses web search, gates to verify all articles were saved, and a cheap model for the summary step.

```json
{
  "version": 1,
  "flows": [
    {
      "name": "ai-news-digest",
      "description": "Fetch the latest AI news and produce a daily digest.",
      "steps": [
        {
          "name": "Fetch articles",
          "position": 0,
          "connectors": ["web_search"],
          "content": "# FETCH ARTICLES\n\n## PURPOSE\n\nFetch the 5 most recent AI news articles and save each one as a separate file.\n\n## WORKFLOW\n\n1. Use `web_search` to find the latest AI news from the past 24 hours\n2. Pick the 5 most significant stories\n3. For each, use `web_fetch` to load the full article\n4. Save each article to `{{run.dir}}/article-N.md` with: headline, author, date, URL, and full text\n\n## RULES\n\n- Save exactly 5 articles, one per file\n- Preserve original content faithfully\n- Do not summarize at this stage",
          "gates": [
            {
              "command": "test -f {{run.dir}}/article-1.md",
              "message": "article-1.md was not saved."
            },
            {
              "command": "test -f {{run.dir}}/article-5.md",
              "message": "article-5.md was not saved."
            }
          ]
        },
        {
          "name": "Summarize",
          "position": 1,
          "agent_alias": "mini",
          "content": "# SUMMARIZE\n\n## PURPOSE\n\nProduce a concise daily digest from the articles in your context.\n\n## WORKFLOW\n\n1. The 5 articles from the previous step are already in your context — do not fetch anything\n2. For each article, write a 2-3 sentence summary capturing the key points\n3. Save to `{{run.dir}}/_result.md`\n\n## RULES\n\n- Use the format: ## 1. Headline\\n**Date:** ...\\nSummary text.\n- Preserve original headlines exactly\n- Do not access the web"
        }
      ]
    }
  ]
}
```

**What this demonstrates:**
- Step-level `connectors` declaring `web_search` only on the step that needs it
- Gates verifying expected output files exist
- `agent_alias: "mini"` on the summary step (cheap model for simple work)
- Step 2 reads Step 1's artifacts automatically via context injection

---

### 2. Code implementation with human review

A 4-step flow that researches a task, proposes approaches for human review, implements the chosen approach with a coding agent, and verifies with tests. Uses all four step types.

```json
{
  "version": 1,
  "flows": [
    {
      "name": "reviewed-feature",
      "description": "Research, propose approaches for review, implement with a coding agent, and verify.",
      "steps": [
        {
          "name": "Research",
          "position": 0,
          "agent_alias": "mini",
          "content": "# RESEARCH\n\n## PURPOSE\n\nUnderstand the task requirements and study the relevant parts of the codebase.\n\n## WORKFLOW\n\n1. Read the task description from context\n2. Explore the codebase to understand the current architecture\n3. Identify the files and modules that will need changes\n4. Write a research summary to `{{run.dir}}/_result.md`\n\n## FORBIDDEN\n\n- Do not modify any source files\n- Do not run git commands"
        },
        {
          "name": "Propose",
          "position": 1,
          "step_type": "hitl",
          "content": "# PROPOSE APPROACHES\n\n## PURPOSE\n\nPresent 2-3 implementation approaches for the user to choose from.\n\n## WORKFLOW\n\n1. Read the research notes from context\n2. Design 2-3 distinct approaches with pros and cons\n3. Write them to `{{run.dir}}/_result.md`\n4. End with: \"Which approach should I implement? (1, 2, or 3)\""
        },
        {
          "name": "Implement",
          "position": 2,
          "step_type": "code",
          "agent_alias": "max",
          "content": "# IMPLEMENT\n\n## PURPOSE\n\nImplement the approach the user chose.\n\n## CONTEXT\n\n- The research notes and proposed approaches are in your context\n- The user's response specifies which approach to implement: {{steps.Propose.user_response}}\n\n## WORKFLOW\n\n1. Implement the chosen approach\n2. Follow existing code conventions\n3. Write a summary of all changes to `{{run.dir}}/_result.md`\n\n## FORBIDDEN\n\n- Do not change scope beyond what was proposed\n- Do not push to remote",
          "gates": [
            {"command": "npm test -- --watchAll=false", "message": "All tests must pass."}
          ],
          "allow_max": true,
          "max_gate_retries": 3
        },
        {
          "name": "Build check",
          "position": 3,
          "agent_alias": "mini",
          "content": "# BUILD CHECK\n\n## PURPOSE\n\nRun the build and verify it succeeds.\n\n## WORKFLOW\n\n1. Run `npm run build`\n2. Write the build output to `{{run.dir}}/_result.md`\n\n## FORBIDDEN\n\n- Do not modify any source files\n- Do not push to remote",
          "gates": [
            {"command": "test -f dist/index.js", "message": "Build output must exist."}
          ]
        }
      ]
    }
  ]
}
```

**What this demonstrates:**
- **`agent`** step (Research) with `mini` alias — cheap model for simple exploration
- **`hitl`** step (Propose) — pauses for human input, no gates
- **`code`** step (Implement) — uses Cursor/Claude Code with `max` alias for complex work
- **`agent`** step (Build check) with `mini` — runs the build and validates output via gates
- `{{steps.Propose.user_response}}` — referencing the human's response in a later step
- `allow_max: true` — escalates to stronger model on last gate retry
- `max_gate_retries: 3` — limits retry attempts
- Constraint progression: research forbids changes, implement forbids pushing

---

### 3. Browser automation with MFA bypass

A flow that logs into a website, handles MFA via human-in-the-loop, and performs an action in the authenticated browser session. The browser persists across consecutive steps that declare it.

```json
{
  "version": 1,
  "flows": [
    {
      "name": "login-and-export",
      "description": "Log into a web app with MFA, then export a report.",
      "steps": [
        {
          "name": "Login",
          "position": 0,
          "connectors": ["browser"],
          "content": "# LOGIN\n\n## PURPOSE\n\nNavigate to the login page and enter credentials.\n\n## WORKFLOW\n\n1. Use `browser_navigate` to go to {{space.TARGET_URL}}\n2. Use the snapshot to find the username and password fields\n3. Use `browser_fill` to enter {{space.USERNAME}} and {{space.PASSWORD}}\n4. Use `browser_click` to submit the form\n5. Take a `browser_screenshot` and save to `{{run.dir}}/after-login.png`\n6. Write the current page state to `{{run.dir}}/_result.md`",
          "gates": [
            {"command": "test -f {{run.dir}}/after-login.png", "message": "Login screenshot must exist."}
          ]
        },
        {
          "name": "MFA",
          "position": 1,
          "step_type": "hitl",
          "connectors": ["browser"],
          "content": "# MFA CODE REQUIRED\n\n## PURPOSE\n\nShow the user the current browser state and ask for the MFA code.\n\n## WORKFLOW\n\n1. Take a `browser_screenshot` and save to `{{run.dir}}/mfa-prompt.png`\n2. Use `browser_snapshot` to describe the current page\n3. Write to `{{run.dir}}/_result.md`: explain that the site is asking for an MFA code and ask the user to provide it"
        },
        {
          "name": "Submit MFA",
          "position": 2,
          "connectors": ["browser"],
          "content": "# SUBMIT MFA\n\n## PURPOSE\n\nEnter the MFA code and complete login.\n\n## WORKFLOW\n\n1. The user's MFA code is: {{steps.MFA.user_response}}\n2. Use `browser_snapshot` to find the MFA input field\n3. Use `browser_fill` to enter the code\n4. Use `browser_click` to submit\n5. Take a `browser_screenshot` to confirm login succeeded\n6. Save confirmation to `{{run.dir}}/_result.md`"
        },
        {
          "name": "Export report",
          "position": 3,
          "connectors": ["browser"],
          "content": "# EXPORT REPORT\n\n## PURPOSE\n\nNavigate to the reports page and export the latest report.\n\n## WORKFLOW\n\n1. Use `browser_navigate` or links in the snapshot to reach the reports section\n2. Find and click the export/download button\n3. Take a `browser_screenshot` of the confirmation\n4. Save it to `{{run.dir}}/attachments/export-confirmation.png`\n5. Write a summary of what was exported to `{{run.dir}}/_result.md`"
        }
      ]
    }
  ]
}
```

**What this demonstrates:**
- Step-level `connectors: ["browser"]` — each step that needs the browser declares it; session persists across consecutive browser steps
- Variables — credentials stored as space variables, not hardcoded
- `hitl` step for MFA — browser stays alive while waiting for the user's code (because the hitl step declares the `"browser"` connector)
- `{{steps.MFA.user_response}}` — passing the MFA code to the next step
- `attachments/` directory — screenshot published in the run summary
- Browser state carries over: step 1 logs in, step 3 still has the session

---

### 4. Conditional steps with IFs

A flow that lints whatever languages are present in the project. Steps are skipped if the language isn't detected.

```json
{
  "version": 1,
  "flows": [
    {
      "name": "polyglot-lint",
      "description": "Lint all detected languages in the project.",
      "steps": [
        {
          "name": "Lint Python",
          "position": 0,
          "agent_alias": "mini",
          "content": "# LINT PYTHON\n\n## PURPOSE\n\nRun the Python linter and capture results.\n\n## WORKFLOW\n\n1. Run `python -m ruff check .`\n2. Save the full output to `{{run.dir}}/_result.md`\n\n## FORBIDDEN\n\n- Do not fix any issues, only report them",
          "ifs": [
            {"command": "test -f pyproject.toml || test -f requirements.txt", "message": "Python project detected"}
          ]
        },
        {
          "name": "Lint JavaScript",
          "position": 1,
          "agent_alias": "mini",
          "content": "# LINT JAVASCRIPT\n\n## PURPOSE\n\nRun the JavaScript linter and capture results.\n\n## WORKFLOW\n\n1. Run `npx eslint .`\n2. Save the full output to `{{run.dir}}/_result.md`\n\n## FORBIDDEN\n\n- Do not fix any issues, only report them",
          "ifs": [
            {"command": "test -f package.json", "message": "Node project detected"},
            {"command": "grep -q eslint package.json", "message": "ESLint is configured"}
          ]
        },
        {
          "name": "Lint Go",
          "position": 2,
          "agent_alias": "mini",
          "content": "# LINT GO\n\n## PURPOSE\n\nRun the Go linter and capture results.\n\n## WORKFLOW\n\n1. Run `golangci-lint run ./...`\n2. Save the full output to `{{run.dir}}/_result.md`\n\n## FORBIDDEN\n\n- Do not fix any issues, only report them",
          "ifs": [
            {"command": "test -f go.mod", "message": "Go project detected"}
          ]
        },
        {
          "name": "Summary",
          "position": 3,
          "agent_alias": "mini",
          "content": "# LINT SUMMARY\n\n## PURPOSE\n\nSummarize the lint results from the previous steps.\n\n## WORKFLOW\n\n1. Read all lint outputs from context (only completed steps are included — skipped steps won't appear)\n2. List any warnings or errors found\n3. Write a summary to `{{run.dir}}/_result.md`"
        }
      ]
    }
  ]
}
```

**What this demonstrates:**
- `ifs` — each lint step only runs if the language is detected
- Multiple IFs on one step (Lint JavaScript) — **all** must pass
- `agent_alias: "mini"` — cheap model for simple command-and-capture steps
- `agent` summary step that reads only the outputs from steps that actually ran
- Skipped steps produce no artifacts, so they don't appear in later context

---

## Creating and managing flows

### Via the Chat assistant

The easiest way. Open **Chat** in the UI, describe what you want to automate, and the assistant will design and import the flow for you.

### Via CLI

```bash
# Create from scratch
llmflows flow create my-flow --description "Custom workflow"
llmflows flow step add --flow my-flow --name research --content steps/research.md --position 0
llmflows flow step add --flow my-flow --name execute --content steps/execute.md --position 1

# Import from JSON
llmflows flow import flows/my-flow.json

# Export all flows
llmflows flow export --output flows.json

# Duplicate an existing flow
llmflows flow create my-variant --copy-from default
```

### Via the UI

Use the visual flow editor to add, reorder, and edit steps directly.
