# Connectors

Connectors give agents access to external services via [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) servers. Each connector runs as a separate process that the daemon manages automatically — starting it when a step needs it and stopping it when it's no longer required.

---

## Built-in connectors

Two connectors ship with llm-flows and are always available:

| ID | Description |
|----|-------------|
| `web_search` | Search the web and fetch page content. Supports DuckDuckGo (default, no API key), Brave Search, Perplexity, and SerpAPI. |
| `browser` | Control a real Chromium browser — navigate, click, fill forms, take screenshots. The session persists across consecutive steps so login state carries over. |

Built-in connectors cannot be removed, only enabled or disabled.

---

## Connector catalog

The catalog contains pre-configured third-party connectors that you can install with one command. Browse it in the UI (**Connectors** page) or via the CLI:

```bash
llmflows connectors catalog
```

| ID | Name | Category | Description |
|----|------|----------|-------------|
| `google_workspace` | Google Workspace | Google Workspace | Gmail, Calendar, Drive, Docs, Sheets, Slides, and Contacts. |
| `youtube` | YouTube | Google Workspace | Search videos, list playlists, get transcripts, and access private YouTube data. |
| `notion` | Notion | Productivity | Search, read, and update Notion pages and databases. |
| `github` | GitHub | Developer | Manage repositories, issues, pull requests, and more. |
| `slack_mcp` | Slack | Productivity | Read and send messages in Slack channels. |
| `linear` | Linear | Developer | Manage issues and projects in Linear. |
| `postgres` | PostgreSQL | Database | Query and explore PostgreSQL databases. |

---

## Adding a connector

### From the UI

Open the **Connectors** page. All available connectors are listed — those from the catalog appear under "Not Connected". Click **Connect** on any connector to install it and open its configuration modal. Fill in the required credentials (API key, token, etc.) and click **Connect** to enable it.

For connectors that require more complex setup (like Google Workspace), the modal offers an **"Ask the agent to configure"** link. This opens a Chat session where the assistant walks you through the full setup process interactively.

### From the CLI

```bash
# Add a catalog connector
llmflows connectors add notion

# Set required credentials
llmflows connectors config notion NOTION_API_KEY ntn_xxx

# Enable it
llmflows connectors enable notion
```

---

## Configuring credentials

Most catalog connectors require API keys or tokens. Set them with:

```bash
llmflows connectors config <server_id> <KEY> <value>
```

For example:

```bash
llmflows connectors config github GITHUB_TOKEN ghp_xxx
llmflows connectors config postgres DATABASE_URL postgresql://user:pass@host:5432/db
llmflows connectors config slack_mcp SLACK_BOT_TOKEN xoxb-xxx
```

Credentials are stored locally in the llm-flows database and passed as environment variables to the connector process at runtime.

---

## Managing connectors

```bash
# List all installed connectors
llmflows connectors list

# Enable / disable
llmflows connectors enable <server_id>
llmflows connectors disable <server_id>

# Remove a custom connector (built-ins can only be disabled)
llmflows connectors remove <server_id>

# Test a connector (requires daemon to be running)
llmflows connectors test <server_id>

# Restart a connector server
llmflows connectors restart <server_id>
```

---

## Using connectors in flows

Connectors are attached **per step** via the `connectors` field. Only the steps that need a connector should declare it.

```json
{
  "name": "fetch-data",
  "position": 0,
  "connectors": ["web_search"],
  "content": "Search the web for the latest AI news..."
}
```

You can also manage flow-level connector defaults with the CLI:

```bash
llmflows flow connectors list <flow-name>
llmflows flow connectors add <flow-name> web_search
llmflows flow connectors remove <flow-name> browser
```

### Session persistence

Consecutive steps that declare the same connector share a single server session. This is especially useful for the `browser` connector — login state, cookies, and open pages carry over from one step to the next.

---

## Configuring web search

The `web_search` connector supports multiple search providers. Configure it in the UI (**Connectors > Web Search**) or via CLI:

```bash
# Use Brave Search (requires API key)
llmflows connectors config web_search WEB_SEARCH_PROVIDER brave
llmflows connectors config web_search BRAVE_API_KEY xxx

# Use Perplexity (requires API key)
llmflows connectors config web_search WEB_SEARCH_PROVIDER perplexity
llmflows connectors config web_search PERPLEXITY_API_KEY xxx
```

DuckDuckGo is the default and requires no API key.

---

## Google Workspace setup

The Google Workspace and YouTube connectors require OAuth credentials from a Google Cloud project. The easiest way to set this up is to ask the **Chat assistant** — it has a built-in skill that walks you through the entire process interactively using `gcloud` CLI and browser automation:

> "Help me set up the Google Workspace connector"

The assistant will guide you through creating a Google Cloud project, enabling the required APIs, configuring OAuth consent, and saving credentials.
