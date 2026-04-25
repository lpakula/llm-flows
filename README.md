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

### 💬 Chat assistant

Not sure where to start? The built-in Chat assistant will guide you. Describe what you want to automate and it will design and build the flow for you. It can also explain how everything works and answer questions about your existing flows and runs — no docs required.

### 📬 Inbox and notifications

The **Inbox** is your central hub for everything that needs your attention — completed results, errors that need a look, and HITL steps waiting for your response. Each entry includes summaries and any attachments (screenshots, reports, files).

### ⏰ Schedules

Every flow can have a cron schedule — hourly, daily, weekdays at 9am, or any custom interval. The daemon picks up scheduled flows automatically.

### 📱 Gateway

Connect external channels to receive notifications, respond to HITL steps from anywhere, and start flows directly from a chat message. Set this up in **Settings > Gateway**.

Available channels:
- **Telegram** — get notified and respond to flows from your phone
- **Slack** — receive updates and approve HITL steps in your workspace

### 🛠️ Built-in agent tools

Every agent step has access to a core set of tools out of the box:

- **Read / Write / Edit** — read, create, and edit files
- **Shell** — run any shell command

### 🔌 Connectors

Connectors give agents access to external services via [MCP](https://modelcontextprotocol.io/) servers. Two are built in:

- **Web search** — search the web and fetch page content, no extra API keys needed
- **Browser** — control a real Chromium browser: navigate, click, fill forms, take screenshots. The session persists across steps so login state carries over

Install more from the **connector catalog** in the UI or CLI — no code required:

- **Google Workspace** — Gmail, Calendar, Drive, Docs, Sheets, Slides
- **YouTube** — search videos, list playlists, get transcripts
- **Notion** — search, read, and update pages and databases
- **GitHub** — manage repositories, issues, and pull requests
- **Slack** — read and send messages in channels
- **Linear** — manage issues and projects
- **PostgreSQL** — query and explore databases

See **[Connectors](docs/connectors.md)** for setup details.

### 🧠 Skills

Steps can load **skills** — reusable instruction sets that give the agent domain-specific knowledge or workflows. Drop a `SKILL.md` file into `.agents/skills/<name>/` and reference it by name in any step. Skills are injected into the agent's prompt at runtime.

### 🧩 Customisable flows

A flow is a sequence of steps. Each step can use a different type, so you can mix and match within a single flow:

- **Agent** — AI agent with access to tools and connectors (file read/write, shell, web search, browser, and any installed connector) for research, analysis, content generation, and automation
- **Code** — delegates to a coding agent (Cursor, Claude Code) for steps that require writing or editing code
- **Human-in-the-loop** — pauses the flow and waits for your input before continuing

Each step can also run on a different model tier — **mini**, **normal**, or **max** — so you use a fast, cheap model for straightforward tasks and a powerful one only where it matters. You can also route steps to **local models** via Ollama or LM Studio for zero API cost.

### 💰 Cost monitoring

Every run tracks token usage and cost across all steps. You can see exactly how much each run costs, which steps are expensive, and set a **max spend** per flow to prevent runaway costs. All of this is visible in the UI on the run detail page.

---

## 📋 Requirements

- Python 3.11+
- Node.js 18+
- An LLM API key (Anthropic, OpenAI, or another supported provider)

## 📖 Documentation

- **[CLI Reference](docs/cli.md)** — all commands
- **[Flow Authoring](docs/flows.md)** — writing flows, steps, and gates
- **[Connectors](docs/connectors.md)** — MCP integrations, catalog, and custom servers
- **[Development](docs/development.md)** — contributing and local setup

## 🤝 Contributing

Contributions, issues, and feedback are welcome.

## License

MIT
