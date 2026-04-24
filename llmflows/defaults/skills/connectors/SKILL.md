---
name: llmflows-connectors
description: Set up and configure connectors (Google Workspace, YouTube, Notion, GitHub, Slack, Linear, Postgres). Use when the user wants to connect a service, configure OAuth, add API keys, or troubleshoot a connector.
---

# Connector Setup Guide

How to obtain API keys and tokens for each connector in llm-flows.

## Agent behavior

1. **Prefer `gcloud` CLI for Google connectors.** Use shell commands (`gcloud projects list`, `gcloud services enable`, etc.) whenever possible. Fall back to browser automation only for steps that `gcloud` cannot handle (OAuth consent screen, credential creation).
2. **For non-Google connectors, use browser automation.** Navigate directly to the **external service portal** — NOT the llm-flows UI. Follow the steps from the guide below, clicking through the portal pages for the user. When you hit a login/auth screen, tell the user: "Please log in in the browser window, then tell me when you're done." Wait for their reply before continuing.
3. **Do NOT offer manual steps** unless the user explicitly asks for them.
4. **NEVER fabricate or invent credential values.** Only use values you actually read from the browser page or received from a CLI/API response.
5. When you have the keys/tokens, **print them for the user to copy-paste** into the connector config in the llm-flows UI.

Do NOT run `llmflows connectors config` commands automatically. Let the user paste the values themselves.

---

## Google Workspace (Gmail, Calendar, Drive, Docs, Sheets, Slides, Contacts)

The Google Workspace connector uses `@alanxchen/google-workspace-mcp`. It handles OAuth automatically — on first use it opens a browser for consent. You only need to set up a Google Cloud project and create OAuth Desktop credentials once.

### Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`)

### Step 1 — Select a Google Cloud project

Run `gcloud projects list --format="table(projectId,name)"` and show the user the list. Ask them to pick one, or create a new project:

```bash
gcloud projects create llm-flows-mcp --name="llm-flows MCP"
```

Set the selected project:

```bash
gcloud config set project PROJECT_ID
```

### Step 2 — Enable APIs (gcloud)

Run a single command to enable all required APIs:

```bash
gcloud services enable \
  gmail.googleapis.com \
  calendar-json.googleapis.com \
  drive.googleapis.com \
  docs.googleapis.com \
  sheets.googleapis.com \
  slides.googleapis.com \
  people.googleapis.com
```

### Step 3 — Configure OAuth consent screen (browser)

Navigate directly to: `https://console.cloud.google.com/auth/overview?project=PROJECT_ID`

If this is the first time setting up OAuth for this project, you'll see a "Get started" or "Configure consent screen" button. Click it.

1. **App name**: "llm-flows" (or whatever the user prefers)
2. **User support email**: select the user's email from the dropdown
3. **Audience / User type**: choose **External** (or Internal if using Google Workspace)
4. **Developer contact email**: enter the user's email
5. Click through to save the basic settings.
6. Navigate to `https://console.cloud.google.com/auth/audience?project=PROJECT_ID`, click **Add users**, add the user's Google account email, and save. This is required because the app is in "Testing" mode.

### Step 4 — Create OAuth Desktop credentials (browser)

Navigate directly to: `https://console.cloud.google.com/apis/credentials/oauthclient?project=PROJECT_ID`

1. **Application type**: select **Desktop app** (NOT Web application)
2. **Name**: "llm-flows" (or leave default)
3. Click **Create**
4. A dialog will show — click **Download JSON** to download `credentials.json`

### Step 5 — Save credentials and enable connector

Move the downloaded `credentials.json` to `~/.google-workspace-mcp/credentials.json`:

```bash
mkdir -p ~/.google-workspace-mcp
mv ~/Downloads/client_secret_*.json ~/.google-workspace-mcp/credentials.json
```

Then tell the user to enable the Google Workspace connector in the llm-flows UI (no config fields needed). On the first tool call, the MCP server will open the browser for OAuth consent — the user clicks "Allow" once. Tokens are cached at `~/.google-workspace-mcp/token.json` automatically.

---

## YouTube

The YouTube connector uses `@mrsknetwork/ytmcp`. It needs **Client ID** and **Client Secret** from the same Google Cloud project used for Google Workspace. It handles its own OAuth flow.

### Setup

If Google Workspace was already set up, the Google Cloud project, consent screen, and test users are already configured. Just enable the YouTube API via gcloud:

```bash
gcloud services enable youtube.googleapis.com
```

Then retrieve the Client ID and Client Secret from the existing OAuth Desktop credentials. Navigate to `https://console.cloud.google.com/apis/credentials?project=PROJECT_ID`, click on the Desktop client, and copy the values. Paste them into the YouTube connector config in the llm-flows UI.

If Google Workspace was NOT set up, follow Steps 1-4 from the Google Workspace section above first (adding `youtube.googleapis.com` to the API enable command), then do the steps above.

---

## Notion

1. Go to `https://www.notion.so/my-integrations`.
2. Click **New integration**.
3. Name it (e.g. "llm-flows"), select the workspace, and click **Submit**.
4. Copy the **Internal Integration Secret** (starts with `ntn_`).
5. In Notion, open the pages/databases you want the integration to access → click **⋯** → **Connect to** → select your integration.
6. Print the API key for the user to paste into the Notion connector config in the llm-flows UI.

---

## GitHub

1. Go to `https://github.com/settings/tokens?type=beta` (Fine-grained tokens) or `https://github.com/settings/tokens` (Classic).
2. Click **Generate new token**.
3. For fine-grained tokens: select the repositories and permissions you need.
   For classic tokens: select scopes like `repo`, `read:org` as needed.
4. Copy the token.
5. Print the token for the user to paste into the GitHub connector config in the llm-flows UI.

---

## Slack

1. Go to `https://api.slack.com/apps` and click **Create New App → From scratch**.
2. Name it (e.g. "llm-flows") and select your workspace.
3. Under **OAuth & Permissions**, add the Bot Token Scopes you need (e.g. `channels:read`, `chat:write`, `users:read`).
4. Click **Install to Workspace** and authorize.
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`).
6. Print the token for the user to paste into the Slack connector config in the llm-flows UI.

---

## Linear

1. Go to `https://linear.app/settings/api`.
2. Under **Personal API keys**, click **Create key**.
3. Copy the key.
4. Print the key for the user to paste into the Linear connector config in the llm-flows UI.

---

## PostgreSQL

No external setup needed — just provide your connection string.

Format: `postgresql://user:password@host:port/database`

Ask the user for their connection string and tell them to paste it into the PostgreSQL connector config in the llm-flows UI.
