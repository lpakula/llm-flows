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
{%- if artifacts %}

---

## Previous Step Artifacts
{%- for art in artifacts %}

### Step {{ art.position }}: {{ art.step_name }}
{%- for file in art.files %}

#### {{ file.name }}

```
{{ file.content }}
```
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

## Output Artifacts

Save any important outputs, findings, or state to: `{{ artifacts_output_dir }}/`
Create the directory if needed. Files you write here will be available to subsequent steps.
{%- endif %}

**When you have completed the instructions above, stop. Do not continue or run additional commands.**
