---
name: llmflows-skills
description: Create and manage skills for llm-flows spaces. Use when the user wants to create a skill, write a SKILL.md, add domain knowledge for agents, or asks about skills.
---

# llm-flows Skills

Skills are prompt documents that give agents domain knowledge during flow execution. They live in the space's `.agents/skills/` directory and can be attached to individual flow steps.

Skills follow the open [Agent Skills](https://agentskills.io) format — they work with llm-flows and many other agent tools (Cursor, Claude Code, Gemini CLI, etc.).

---

## Directory structure

```
<space-root>/
└── .agents/
    └── skills/
        ├── my-skill/
        │   ├── SKILL.md           # Required: metadata + instructions
        │   ├── references/        # Optional: detailed docs
        │   └── scripts/           # Optional: executable code
        └── another-skill/
            └── SKILL.md
```

- The **directory name** is the skill identifier (used in flow step `skills: [...]` arrays)
- Skills are auto-discovered — the UI and daemon scan `.agents/skills/` for subdirectories with `SKILL.md`
- A skill can be just a `SKILL.md`, or include additional files the agent reads/executes on demand

## SKILL.md format

Every skill file has YAML frontmatter followed by markdown content:

```markdown
---
name: my-skill
description: Deploys the application to production. Use when the user asks to deploy, release, or ship to production.
---

# Deployment

Instructions, reference material, examples, constraints.
The agent reads this file when the skill is activated.
```

### Frontmatter fields

| Field | Required | Constraints |
|-------|----------|-------------|
| `name` | Yes | Max 64 chars. Lowercase letters, numbers, hyphens only. Must match directory name. |
| `description` | Yes | Max 1024 chars. What the skill does AND when to use it. Write in third person. |
| `compatibility` | No | Environment requirements — intended agent type, required tools, etc. |

### Name rules

- Lowercase alphanumeric + hyphens: `deploy`, `code-review`, `data-pipeline`
- Must match the parent directory name
- No consecutive hyphens, no leading/trailing hyphens

### Writing good descriptions

The description is how agents decide whether to activate the skill. Include **what** it does and **when** to use it. Use specific keywords.

Good:
```yaml
description: Extracts text and tables from PDF files, fills forms, merges documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.
```

Bad:
```yaml
description: Helps with PDFs.
```

Always write in third person ("Deploys the app...", not "I deploy the app..." or "Use this to deploy...").

## Writing effective skill content

### Be concise — assume the agent is smart

Only add context the agent doesn't already have. Every token in your skill competes with conversation history and step content.

Good (~50 tokens):
```markdown
## Extract PDF text

Use pdfplumber for text extraction:

    import pdfplumber
    with pdfplumber.open("file.pdf") as pdf:
        text = pdf.pages[0].extract_text()
```

Bad (~150 tokens):
```markdown
## Extract PDF text

PDF (Portable Document Format) files are a common file format that contains
text, images, and other content. To extract text from a PDF, you'll need to
use a library. There are many libraries available...
```

### Set appropriate degrees of freedom

- **High freedom** (text instructions) — when multiple approaches are valid and context matters
- **Medium freedom** (templates with parameters) — when a preferred pattern exists but variation is acceptable
- **Low freedom** (exact scripts/commands) — when operations are fragile and consistency is critical

### Keep SKILL.md under 500 lines

Move detailed reference material to separate files. The agent loads `SKILL.md` when the skill activates, but reads additional files only when needed.

```markdown
# API Integration

## Quick start
[Core instructions here — under 500 lines]

## Detailed reference
- API endpoints: See [references/endpoints.md](references/endpoints.md)
- Error codes: See [references/errors.md](references/errors.md)
- Examples: See [references/examples.md](references/examples.md)
```

Keep file references **one level deep** from SKILL.md — avoid chains of files referencing other files.

### Use consistent terminology

Pick one term and stick with it throughout. Don't mix "API endpoint" / "URL" / "route" / "path" for the same concept.

## Attaching skills to flow steps

Skills are referenced by directory name in a step's `skills` array:

```json
{
  "name": "implement",
  "position": 1,
  "content": "...",
  "skills": ["deploy", "code-review"]
}
```

When the daemon launches the step, it includes a reference to each skill in the agent's prompt. The agent reads each skill file before starting work.

## What makes a good skill

**Good skills:**

- Project-specific conventions — coding standards, architecture patterns, naming rules
- Domain knowledge — API references, data models, business rules
- Workflow instructions — deployment procedures, review checklists, testing strategies
- Tool usage — how to use project-specific tools, scripts, or services

**Bad skills:**

- Generic programming advice the agent already knows
- Extremely long single-file docs (split into SKILL.md + references/)
- Duplicating information already in flow step content
- Vague names like `helper`, `utils`, `tools`

## Example: a deployment skill

```
deploy/
├── SKILL.md
└── scripts/
    └── deploy.sh
```

```markdown
---
name: deploy
description: Deploys the application to production. Use when the user asks to deploy, release, or ship changes to production.
---

# Deployment

## Build

Run `npm run build` from the project root. Output goes to `dist/`.

## Pre-deploy checks

1. All tests must pass: `npm test`
2. Lint must be clean: `npm run lint`
3. Build must succeed with no warnings

## Deploy

Run exactly: `./scripts/deploy.sh --env production`

The script expects `DEPLOY_KEY` to be set as a space variable.

## Rollback

If deployment fails, run `./scripts/rollback.sh` to revert.
```

## Viewing skills in the UI

Navigate to a space and click the **Skills** tab. All discovered skills are shown as cards with their name and description. Click a card to preview the full `SKILL.md` content.
