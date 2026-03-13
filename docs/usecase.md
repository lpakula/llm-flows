# Analyse → Execute across multiple runs

You can split a complex task across runs — the agent carries full context from the previous run.

This example uses the GitHub integration. You can create a flow where comments on a GitHub issue trigger runs and the agent posts results back as comments.

```
Refactor the payment service to support multiple currencies

@llmflows --alias analyse
```

The agent analyses the codebase and posts a detailed implementation plan as a GitHub comment. You review it, then trigger the next run:

```
I approve the plan

@llmflows --alias execute
```

A cheaper model picks up the plan and delivers the changes — execution burns a lot of output tokens, so this is where model choice has the biggest cost impact. You stay in control of the direction, the agent handles the work.
