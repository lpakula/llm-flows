# Example: Research → Execute across separate runs

You can split a complex task across multiple runs and keep the context between them.

This example uses the GitHub integration. A comment on an issue triggers one run to research the task, then a second run to execute it.

> Refactor the payment service to support multiple currencies

```bash
@llmflows --alias research
```

The first run researches the codebase and posts a clear implementation plan back to the GitHub issue. After review, trigger the next run:

> I approve the plan

```bash
@llmflows --alias execute
```

The `execute` alias can be configured to use a different model from `research`. This is useful when you want a stronger model for planning and a cheaper or more targeted model for the execution phase.
