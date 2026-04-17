# ERROR SUMMARY

This flow run **failed** with outcome `{{ outcome }}` at step `{{ failed_step }}`.

{{ error_details }}

{% if log_tail -%}
## Failing step log (last lines)

```
{{ log_tail }}
```
{% endif -%}

Read all previous step results above, then write a concise error analysis to `{{ artifacts_dir }}/summary.md`. Then stop.

## RULES

- Start with a one-line verdict: what failed and why
- Explain the root cause based on the error details, log excerpt, and artifacts
- If relevant, note what completed successfully before the failure
- Keep it concise — focus on diagnosis, not process
- Write in markdown format
- After writing the summary file, stop
