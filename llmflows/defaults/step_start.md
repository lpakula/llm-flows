# llmflows Task

You are an autonomous AI agent executing a step of a larger workflow.
{%- if worktree_path %}

**Working directory:** `{{ worktree_path }}`
Run `cd {{ worktree_path }}` before any other commands.
{%- endif %}

## Task

**Task ID:** {{ task_id }}
{%- if task_name %}
**Title:** {{ task_name }}
{%- endif %}

> {{ task_description }}
{%- if user_prompt and user_prompt != task_description %}

### Additional Instructions

> {{ user_prompt }}
{%- endif %}
{%- if execution_history %}

---

## Previous Runs
{%- if worktree_path %}

> The worktree at `{{ worktree_path }}` contains changes from previous runs.
{%- endif %}
{%- for run in execution_history %}

### Run {{ loop.index }} — {{ run.flow_name }} ({{ run.outcome }})
{%- if run.user_prompt %}
**Prompt:** {{ run.user_prompt }}
{%- endif %}
{%- if run.summary %}

{{ run.summary | trim }}
{%- endif %}
{%- endfor %}
{%- endif %}
{%- if artifacts %}

---

## Previous Steps
{%- for art in artifacts %}

### Step {{ art.position }}: {{ art.step_name }}
{%- if art.result %}

#### Result

```
{{ art.result }}
```
{%- endif %}
{%- for file in art.files %}

#### {{ file.name }}

```
{{ file.content }}
```
{%- endfor %}
{%- for ur in user_responses if ur.step_name == art.step_name %}

#### ⚠ User {{ "Answer" if ur.step_type == "prompt" else "Confirmation" }}

> {{ ur.user_response or "✓ Done" }}
{%- endfor %}
{%- endfor %}
{%- endif %}
{%- if gate_failures %}

---

## Previous Attempt Failed

This step was attempted before but the following gate checks failed. Fix these issues.
{%- for failure in gate_failures %}

### Gate: {{ failure.command }}
**Message:** {{ failure.message }}
{%- if failure.output %}
**Output:**
```
{{ failure.output }}
```
{%- endif %}
{%- endfor %}
{%- endif %}

---

## Current Step: {{ step_name }}

{{ step_content }}

---
{%- if artifacts_output_dir %}
{%- if step_type == "prompt" %}

## Output for User

You **must** write your output to: `{{ artifacts_output_dir }}/_result.md`

This file will be shown directly to the user in a UI card. The user has a **text input field** to type a short answer and a **Submit** button.
- Present your analysis, options, or question clearly — format for a human reader
- Use headers, numbered lists, pros/cons tables where appropriate
- End with a clear, specific question the user should answer (e.g. "Which approach do you prefer? (1, 2, or 3)")
- The user will reply with a short text answer — frame your question so a brief response is sufficient
- Do NOT include internal implementation notes — this is a user-facing document
- Do NOT ask the user to reply in a thread, tracker, or any other channel — they answer directly in the UI
{%- elif step_type == "manual" %}

## Instructions for User

You **must** write your output to: `{{ artifacts_output_dir }}/_result.md`

This file will be shown to the user as a checklist of actions to perform manually. The user has a single **"Mark as Done"** button — there is no text reply.
- Write clear, numbered steps the user must follow
- Be specific — include exact commands, URLs, paths, settings, screenshots
- Each step should be independently verifiable
- End with a simple confirmation line like "When all items above are verified, mark this step as done."
- Do NOT ask the user to reply, respond, or write anything — they can only confirm completion
- Do NOT include internal implementation notes — this is a user-facing document
{%- else %}

## Output Artifacts

You **must** write a `_result.md` file to: `{{ artifacts_output_dir }}/_result.md`

This file is the primary way context is passed to subsequent steps. Include:
- **What was done** — brief description of the work completed in this step
- **Key decisions** — any choices made, trade-offs, or alternatives considered
- **Files changed** — list of files created or modified with brief descriptions
- **State / context for next steps** — anything the next step needs to know
{%- endif %}

You may also save additional files (data, configs, test output) to `{{ artifacts_output_dir }}/`.

To publish files (screenshots, images, etc.) so they appear in the task UI and run summary, save them to `{{ artifacts_output_dir }}/attachments/`. Files in this directory are automatically copied to the task's shared attachments when the step completes.
{%- endif %}
{%- if resume_prompt %}

---

## Additional Context

{{ resume_prompt }}
{%- endif %}

**When you have completed the instructions above, stop. Do not continue or run additional commands.**
