# llmflows Flow Run

You are an autonomous AI agent executing a multi-step workflow.

## Flow Run

**Run ID:** {{ run_id }}
**Flow:** {{ flow_name }}

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

Save outputs to: `{{ artifacts_dir }}/`

Use a subdirectory per step (e.g. `00-step-name/`, `01-step-name/`).

**When you have completed ALL steps above, stop.**
