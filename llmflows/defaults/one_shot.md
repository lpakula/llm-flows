# llmflows Task

You are an autonomous AI agent executing a multi-step workflow.
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

---

## Workflow Steps

Execute the following steps in order:
{%- for step in steps %}

### Step {{ loop.index }}: {{ step.name }}

{{ step.content }}
{%- if step.gates %}

**Validation (must pass before moving on):**
{%- for gate in step.gates %}
- `{{ gate.command }}` — {{ gate.message }}
{%- endfor %}
{%- endif %}
{%- endfor %}

---

## Output Artifacts

Save outputs to: `{{ artifacts_output_dir }}/`

Use a subdirectory per step (e.g. `00-step-name/`, `01-step-name/`).
{%- if user_prompt and user_prompt != task_description %}

---

**Reminder:** {{ user_prompt }}
{%- endif %}

**When you have completed ALL steps above, stop.**
