# Cursor IDE Integration

`llm-flows` is designed for **fully automated background agents** — a daemon picks up tasks, launches an agent CLI, and drives the flow unattended. However, the protocol works with any agent that can run shell commands, including interactive sessions in Cursor IDE.

---

## ✏️ Cursor IDE 

Add `.cursor/commands/llmflows-start.md` to your project to trigger flows with `/llmflows-start`:

```markdown
---
description: Initialize llm-flows protocol
---

When starting a task, run:

llmflows task create -t "<title>" -d "<description>" --flow "<flow-name>" --inline

If the user doesn't specify a flow name, use "default".

Then follow the protocol instructions in the output.
```

You can enforce llm-flows on any task by invoking `/llmflows-start` directly in the Cursor agent and providing the task description — the agent will bootstrap the protocol and follow it from there.

> [!NOTE]
> Cursor IDE is designed for human-in-the-loop workflows. Unlike background daemon runs, the agent will pause and wait for your input between steps and won't operate fully autonomously — but it will still follow the llm-flows protocol, enforce gates, and track the run. 
