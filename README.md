<p align="center">
  <h1 align="center">llm-flows</h1>
  <p align="center"><strong>AI automations that run in the background.</strong></p>
  <p align="center">Build, schedule, and monitor workflows powered by AI agents — no coding required.</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-22c55e?style=flat-square" alt="MIT License">
  <img src="https://img.shields.io/badge/UI%20%2B%20CLI-8b5cf6?style=flat-square&logo=windowsterminal&logoColor=white" alt="UI + CLI">
  <img src="https://img.shields.io/badge/local--first-f59e0b?style=flat-square&logo=homeassistant&logoColor=white" alt="Local-first">
</p>

---

## What is llm-flows?

`llm-flows` is a local platform for building and running AI automations. You describe what you want to automate, and `llm-flows` takes care of the rest — breaking the work into steps, running each one with an AI agent, and delivering the results to you.

Everything runs on your machine. No cloud lock-in, no per-run fees beyond your LLM API costs.

> **Example: "Summarize today's top AI news"**
>
> A flow like this runs in the background and delivers a digest straight to your inbox:
>
> 1. 🔍 **Fetch** — the agent searches the web for the latest AI news articles
> 2. 📝 **Summarize** — the agent reads all articles and writes a concise summary of the top 5 stories
> 3. 📬 **Done** — the summary lands in your inbox (and optionally Telegram or Slack)
>
> Set it to run daily at 9am, and you'll never miss an important story again.

---

## ⚡ Get started in 3 steps

### 1. Install and register your LLM API key

```bash
curl -fsSL https://raw.githubusercontent.com/lpakula/llm-flows/main/scripts/install.sh | bash
```

Launch the UI and follow the welcome screen to enter your API key (Anthropic, OpenAI, or another provider):

```bash
llmflows ui
```

### 2. Ask the Chat assistant to build your flow

Open **Chat** in the sidebar and describe what you want to automate. The assistant will design the flow for you — just confirm and it's ready.

> 💬 **You:** "I want a daily summary of the top 5 AI news stories"
>
> 🤖 **Assistant:** *designs a 2-step flow, explains each step, and imports it for you*

You don't need to know anything about steps, gates, or flow structure. The assistant handles all the technical details.

### 3. Run it — manually or on a schedule

Click **Run** in the UI to execute the flow immediately, or set a schedule (daily, hourly, weekdays only, etc.) and let it run automatically.

Monitor progress in the UI, and find your results in the **Inbox** when each run completes.

---

## ✨ Key features

### 🔍 Built-in web search

Agents can search the web and fetch page content out of the box — no external tools or API keys required. Use it for research, news monitoring, data gathering, or any step that needs live information from the internet.

### 🌐 Browser automation

Agents can control a real Chromium browser — navigating pages, clicking buttons, filling forms, and taking screenshots. The browser session persists across all steps in a flow, so login state and cookies carry over.

Runs in **headless** mode by default (no visible window), or switch to **headed** mode to watch the agent work in real time.

### 🙋 Human-in-the-loop (HITL)

Some automations need a human touch. HITL steps pause the flow and ask for your input before continuing. Use this for:

- **🔐 MFA / login bypass** — the agent logs into a website, hits the MFA prompt, and asks you for the code. You respond, and the agent continues with the authenticated session.
- **✅ Approvals** — review a plan or proposed changes before the agent executes them.
- **🔀 Decision points** — the agent presents options and you pick the direction.

### 📬 Inbox and notifications

The **Inbox** is your central hub. Completed runs show up here with summaries and any attachments (screenshots, reports, files). HITL steps also appear in the inbox, waiting for your response.

### 📱 Gateway

Connect external channels to receive notifications, respond to HITL steps from anywhere, and start flows directly from a chat message. Set this up in **Settings > Gateway**.

Available channels:
- **Telegram** — get notified and respond to flows from your phone
- **Slack** — receive updates and approve HITL steps in your workspace

### ⏰ Schedules

Every flow can have a cron schedule — hourly, daily, weekdays at 9am, or any custom interval. The daemon picks up scheduled flows automatically.

### 💬 Chat assistant

The built-in Chat helps you get started without reading any documentation. It can:

- Explain how `llm-flows` works
- Design and build flows based on your description
- Answer questions about your existing flows and runs

---

### 🎯 Smart model routing

Every flow is split into steps, and each step can run on a different agent tier — **mini**, **normal**, or **max**. This means a single flow can use a fast, cheap model for straightforward tasks (fetching data, formatting output) and a powerful model only for the steps that need complex reasoning.

You can also route steps to **local models** via Ollama or LM Studio — run simple steps entirely on your machine with zero API cost.

You control the cost without sacrificing quality where it matters.

### 💰 Cost monitoring

Every run tracks token usage and cost across all steps. You can see exactly how much each run costs, which steps are expensive, and set a **max spend** per flow to prevent runaway costs. All of this is visible in the UI on the run detail page.

---

## 🏗️ How it works

A **flow** is an ordered list of **steps**. Each step runs as a separate AI agent process:

1. The **daemon** picks up a queued run and starts the first step
2. The agent executes the step's instructions and produces output
3. Optional **gates** (automated checks) verify the output — if a check fails, the agent retries with feedback on what went wrong
4. Output from completed steps is automatically passed as context to the next step
5. After the last step, a summary is generated and delivered to your inbox

This step-by-step approach makes automations more reliable than a single long AI run — each step is focused, verifiable, and recoverable.

---

## 📋 Requirements

- Python 3.11+
- Node.js 18+
- An LLM API key (Anthropic, OpenAI, or another supported provider)

## 📖 Documentation

- **[CLI Reference](docs/cli.md)** — all commands
- **[Flow Authoring](docs/flows.md)** — writing flows, steps, and gates
- **[Development](docs/development.md)** — contributing and local setup

## 🤝 Contributing

Contributions, issues, and feedback are welcome.

## License

MIT
