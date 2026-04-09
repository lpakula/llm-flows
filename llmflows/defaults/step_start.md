# llmflows Task

You are an autonomous AI agent executing a step of a larger workflow.
{%- if worktree_path %}

**Working directory:** `{{ worktree_path }}`
Run `cd {{ worktree_path }}` before any other commands.
{%- endif %}

## Task

**Task ID:** {{ task_id }}

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

## Previous Step Artifacts
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
{%- endfor %}
{%- endif %}
{%- if previous_step_log %}

---

## Previous Step Agent Log

The following is the tail of the previous step's agent output. Use it to understand what was done, what decisions were made, and what issues were encountered.

```
{{ previous_step_log }}
```
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

## Output Artifacts

You **must** write a `_result.md` file to: `{{ artifacts_output_dir }}/_result.md`

This file is the primary way context is passed to subsequent steps. Include:
- **What was done** — brief description of the work completed in this step
- **Key decisions** — any choices made, trade-offs, or alternatives considered
- **Files changed** — list of files created or modified with brief descriptions
- **State / context for next steps** — anything the next step needs to know

You may also save additional files (data, configs, test output) to `{{ artifacts_output_dir }}/`.
{%- endif %}
{%- if resume_prompt %}

---

## Additional Context

{{ resume_prompt }}
{%- endif %}

**When you have completed the instructions above, stop. Do not continue or run additional commands.**
