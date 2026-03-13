# Using llm-flows with Cloud Agents

Cloud agents (Cursor Automations, GitHub Copilot, etc.) run in hosted environments where you don't control the runner. `llm-flows` works in these environments via its **inline mode** — no daemon required.

## How it works

Instead of a background daemon orchestrating the run, the agent itself drives the protocol step-by-step. The flow is loaded from a file in your repo. 

## Setup

### 1. Install llm-flows

Install the `llm-flows` package inside the VM in the Initialize script:

```bash
pipx install git+https://github.com/lpakula/llm-flows
```

### 2. Add a flow file to your repo

Place a flow definition at a path the agent can read, e.g. `flows/my-flow.json`. See the [flow format docs](./flows.md) or use one of the [example flows](../flows/).

Load the flow at the start of each run:

```bash
llmflows flow load flows/my-flow.json
```

### 3. Add the system prompt

Add this to your agent's system prompt or automation instructions to enforce the llm-flows protocol from the start:

```
When starting a task, run:

llmflows task create -t "<title>" -d "<description>" --flow my-flow --inline --no-worktree

Then follow the protocol instructions in the output.
```


