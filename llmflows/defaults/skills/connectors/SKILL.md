# Connector Setup Guide

How to obtain API keys and tokens for each connector in llm-flows.

## Agent behavior

1. When the user asks to set up a connector, ask: **"Do you want me to walk you through it step by step, or should I open the browser and do it for you?"**
2. **If manual**: Show the relevant setup steps as text from the sections below. Answer follow-up questions as needed.
3. **If browser automation**: Navigate directly to the **external service portal** (e.g. `https://console.cloud.google.com`, `https://github.com/settings/tokens`, etc.) — NOT the llm-flows UI. Follow the steps from the guide below, clicking through the portal pages for the user. When you hit a login/auth screen, tell the user: "Please log in in the browser window, then tell me when you're done." Wait for their reply before continuing.
4. When you obtain the keys/tokens, give them to the user to paste in the llm-flows Connectors page.

---

## Google Services (Gmail, Google Drive, Google Calendar, YouTube)

All Google connectors need three values: **Client ID**, **Client Secret**, and **Refresh Token**.

### Step 1 — Create a Google Cloud project

1. Go to <https://console.cloud.google.com/projectcreate> and create a new project (e.g. "llm-flows").
2. Select the project from the top dropdown.

### Step 2 — Enable APIs

Go to **APIs & Services → Library** and enable the APIs you need:

| Connector        | API to enable                |
|------------------|------------------------------|
| Gmail            | Gmail API                    |
| Google Drive     | Google Drive API             |
| Google Calendar  | Google Calendar API          |
| YouTube          | YouTube Data API v3          |

### Step 3 — Configure OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** (or Internal if using Workspace).
3. Fill in app name, support email, and developer email.
4. Under **Scopes**, add the scopes for your enabled APIs:
   - Gmail: `https://www.googleapis.com/auth/gmail.modify`
   - Drive: `https://www.googleapis.com/auth/drive`
   - Calendar: `https://www.googleapis.com/auth/calendar`
   - YouTube: `https://www.googleapis.com/auth/youtube.readonly`
5. Under **Test users**, add your Google account email.

### Step 4 — Create OAuth credentials

1. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Choose **Web application**.
3. Under **Authorized redirect URIs**, add: `https://developers.google.com/oauthplayground`
4. Copy the **Client ID** and **Client Secret**.

### Step 5 — Get a Refresh Token via OAuth Playground

1. Go to <https://developers.google.com/oauthplayground>.
2. Click the gear icon (top-right) → check **Use your own OAuth credentials**.
3. Enter your Client ID and Client Secret.
4. In the left panel, select the scopes for your connector (same as Step 3).
5. Click **Authorize APIs** → sign in with your Google account → grant access.
6. Click **Exchange authorization code for tokens**.
7. Copy the **Refresh Token**.

### Step 6 — Paste into llm-flows

In the Connectors page, click **Connect** on Gmail / Google Drive / Google Calendar / YouTube, then paste:

- **Client ID** — from Step 4
- **Client Secret** — from Step 4
- **Refresh Token** — from Step 5

---

## Notion

1. Go to <https://www.notion.so/my-integrations>.
2. Click **New integration**.
3. Name it (e.g. "llm-flows"), select the workspace, and click **Submit**.
4. Copy the **Internal Integration Secret** (starts with `ntn_`).
5. In Notion, open the pages/databases you want the integration to access → click **⋯** → **Connect to** → select your integration.
6. In llm-flows, click **Connect** on Notion and paste the token as **NOTION_API_KEY**.

---

## GitHub

1. Go to <https://github.com/settings/tokens?type=beta> (Fine-grained tokens) or <https://github.com/settings/tokens> (Classic).
2. Click **Generate new token**.
3. For fine-grained tokens: select the repositories and permissions you need.
   For classic tokens: select scopes like `repo`, `read:org` as needed.
4. Copy the token.
5. In llm-flows, click **Connect** on GitHub and paste it as **GITHUB_TOKEN**.

---

## Slack

1. Go to <https://api.slack.com/apps> and click **Create New App → From scratch**.
2. Name it (e.g. "llm-flows") and select your workspace.
3. Under **OAuth & Permissions**, add the Bot Token Scopes you need (e.g. `channels:read`, `chat:write`, `users:read`).
4. Click **Install to Workspace** and authorize.
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`).
6. In llm-flows, click **Connect** on Slack and paste it as **SLACK_BOT_TOKEN**.

---

## Linear

1. Go to <https://linear.app/settings/api>.
2. Under **Personal API keys**, click **Create key**.
3. Copy the key.
4. In llm-flows, click **Connect** on Linear and paste it as **LINEAR_API_KEY**.

---

## PostgreSQL

No external setup needed — just provide your connection string.

Format: `postgresql://user:password@host:port/database`

In llm-flows, click **Connect** on PostgreSQL and paste your connection string as **DATABASE_URL**.
