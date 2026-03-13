# Analyse → Execute as a separate runs

You can split a complex task across runs — the agent carries full context from the previous run.

This example uses the GitHub integration. You can create a flow where comments on a GitHub issue trigger runs and the agent posts results back as comments.

> Refactor the payment service to support multiple currencies

```bash
@llmflows --alias analyse
```

The agent analyses the codebase and posts a detailed implementation plan as a GitHub comment. You review it, then trigger the next run:

> I approve the plan

```bash
@llmflows --alias execute
```

The `execute` alias can be configured to use a cheaper model — writing code burns a lot of output tokens, so this is where model choice has the biggest cost impact. You stay in control of the direction, the agent handles the work.
