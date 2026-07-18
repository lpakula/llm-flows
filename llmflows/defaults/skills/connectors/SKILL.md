---
name: llmflows-connectors
description: Set up and configure connectors (Google Workspace, YouTube, Google Tasks, Notion, GitHub, Slack, Linear, Postgres). Use when the user wants to connect a service, configure OAuth, add API keys, or troubleshoot a connector.
---

# Connector Setup Guide

How to obtain API keys and tokens for each connector in llm-flows.

## Agent behavior

0. **No space required.** Connector setup works from Chat without a registered space or running daemon. Start using browser tools immediately when available.
1. **Do not use `gcloud`.** Chat/runner containers do not include the Google Cloud SDK. For all Google Cloud setup (pick project, enable APIs, OAuth consent, create credentials), use **browser automation** on Google Cloud Console.
2. **For non-Google connectors, use browser automation.** Navigate directly to the **external service portal** — NOT the llm-flows UI. Follow the steps from the guide below, clicking through the portal pages for the user. When you hit a login/auth screen, tell the user: "Please log in in the browser window, then tell me when you're done." Wait for their reply before continuing.
3. **For Notion, always create a personal access token (PAT).** Do **not** create an internal connection unless the user explicitly asks for a team-owned bot with limited page access. PATs use the user's existing page permissions — no per-page sharing step.
4. **Do NOT offer manual steps** unless the user explicitly asks for them. Do **not** ask the user to run shell commands on their host for Google setup.
5. **NEVER fabricate or invent credential values.** Only use values you actually read from the browser page, a local file, or a CLI/API response.
6. When you have the keys/tokens, **print them for the user to copy-paste** into the connector config in the llm-flows UI.

Do NOT run `llmflows connectors config` commands automatically. Let the user paste the values themselves.

---

## Google Workspace (Gmail, Calendar, Drive, Docs, Sheets, Slides, Contacts)

The Google Workspace connector uses `@alanxchen/google-workspace-mcp`. It handles OAuth automatically — on first use it opens a browser for consent. You only need to set up a Google Cloud project and create OAuth Desktop credentials once.

When this connector is enabled on a step, llm-flows also attaches built-in Gmail helpers: `archive_email` (remove INBOX) and `remove_label`. No separate connector setup is required.

### Discover the Google Cloud project ID

**Do not ask the user for the project name unless discovery fails.**

1. Read `~/.google-workspace-mcp/credentials.json` (inside the chat container this is often `/root/.google-workspace-mcp/credentials.json` when mounted, or the host path via `$LLMFLOWS_USER_HOME/.google-workspace-mcp/credentials.json`).
2. Use the JSON field `installed.project_id` or `web.project_id` as `PROJECT_ID`.
3. If that file is missing, open the Cloud Console project picker in the browser (`https://console.cloud.google.com/cloud-resource-manager`) and let the user pick or create a project. Prefer creating/using a project named **llm-flows** (project id often `llm-flows` or `llm-flows-mcp`) unless they already have one.

Use `PROJECT_ID` in every Console URL below (`?project=PROJECT_ID`).

### Step 1 — Enable APIs (browser)

Navigate to each API library page (or the API Library search) with the project selected and click **Enable** if not already enabled:

- `https://console.cloud.google.com/apis/library/gmail.googleapis.com?project=PROJECT_ID`
- `https://console.cloud.google.com/apis/library/calendar-json.googleapis.com?project=PROJECT_ID`
- `https://console.cloud.google.com/apis/library/drive.googleapis.com?project=PROJECT_ID`
- `https://console.cloud.google.com/apis/library/docs.googleapis.com?project=PROJECT_ID`
- `https://console.cloud.google.com/apis/library/sheets.googleapis.com?project=PROJECT_ID`
- `https://console.cloud.google.com/apis/library/slides.googleapis.com?project=PROJECT_ID`
- `https://console.cloud.google.com/apis/library/people.googleapis.com?project=PROJECT_ID`

### Step 2 — Configure OAuth consent screen (browser)

Navigate directly to: `https://console.cloud.google.com/auth/overview?project=PROJECT_ID`

If this is the first time setting up OAuth for this project, you'll see a "Get started" or "Configure consent screen" button. Click it.

1. **App name**: "llm-flows" (or whatever the user prefers)
2. **User support email**: select the user's email from the dropdown
3. **Audience / User type**: choose **External** (or Internal if using Google Workspace)
4. **Developer contact email**: enter the user's email
5. Click through to save the basic settings.

#### Publish to production (required)

Apps left in "Testing" mode issue tokens that **expire after 7 days**. To avoid this, publish the app to production:

1. Navigate to `https://console.cloud.google.com/auth/audience?project=PROJECT_ID`
2. Under **Publishing status**, click **Publish App** and confirm.
3. The status should change from "Testing" to "In production".

Because the app only requests non-sensitive or basic scopes and is used by the project owner, Google does **not** require a verification review — the app can be published immediately. No test users need to be added.

### Step 3 — Create OAuth Desktop credentials (browser)

Navigate directly to: `https://console.cloud.google.com/apis/credentials/oauthclient?project=PROJECT_ID`

1. **Application type**: select **Desktop app** (NOT Web application)
2. **Name**: "llm-flows" (or leave default)
3. Click **Create**
4. A dialog will show — click **Download JSON** to download `credentials.json`

### Step 4 — Save credentials and enable connector

OAuth client JSON must live on the **host** at `~/.google-workspace-mcp/credentials.json` (mounted into chat/runners as `/root/.google-workspace-mcp/`). That path is what every Google connector and Docker run uses — not a file inside the image.

**Preferred (works in Docker chat):** after Create, open the credential details (or the download dialog), copy the JSON (or Client ID + Secret), and **write the full Desktop client JSON** to `/root/.google-workspace-mcp/credentials.json` with the `write` tool. Shape:

```json
{
  "installed": {
    "client_id": "...",
    "project_id": "PROJECT_ID",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "...",
    "redirect_uris": ["http://localhost"]
  }
}
```

**Fallback:** if the browser downloaded `client_secret_*.json` to the host Downloads folder and you cannot read it from the container, tell the user to move it once:

```bash
mkdir -p ~/.google-workspace-mcp
mv ~/Downloads/client_secret_*.json ~/.google-workspace-mcp/credentials.json
```

Then tell the user to enable the Google Workspace connector in the llm-flows UI (no config fields needed). On the first tool call, the MCP server runs OAuth (browser on host, or device flow inside runners) and caches `token.json` next to `credentials.json`.

---

## YouTube

The YouTube connector uses `@mrsknetwork/ytmcp`. It needs **Client ID** and **Client Secret** from the same Google Cloud project used for Google Workspace. It handles its own OAuth flow.

### Setup

If Google Workspace was already set up, resolve `PROJECT_ID` from `~/.google-workspace-mcp/credentials.json` (see above). Enable the YouTube API in the browser:

`https://console.cloud.google.com/apis/library/youtube.googleapis.com?project=PROJECT_ID`

Then open `https://console.cloud.google.com/apis/credentials?project=PROJECT_ID`, open the Desktop OAuth client, copy **Client ID** and **Client Secret**, and print them for the user to paste into the YouTube connector config.

If Google Workspace was NOT set up, follow the Google Workspace section first (also enable the YouTube API), then do the steps above.

---

## Google Tasks

The Google Tasks connector uses `@scottie-will/google-tasks-mcp`. It reuses the same Desktop OAuth client JSON as Google Workspace (`~/.google-workspace-mcp/credentials.json`) and stores its **own** user tokens at `~/.config/google-tasks-mcp/tokens.json`.

The Workspace `token.json` is **not** enough — Tasks needs a separate OAuth consent for `https://www.googleapis.com/auth/tasks`.

### Setup (all steps required — do not stop after enabling the API)

1. Resolve `PROJECT_ID` from `~/.google-workspace-mcp/credentials.json` (see Google Workspace section). If that file is missing, complete Google Workspace setup first.
2. Enable the Tasks API in the browser:  
   `https://console.cloud.google.com/apis/library/tasks.googleapis.com?project=PROJECT_ID`
3. Tell the user to enable/Connect **Google Tasks** in the llm-flows UI (credentials path defaults to `$HOME/.google-workspace-mcp/credentials.json`).
4. **Complete Tasks OAuth now** (mandatory — enabling the API alone is not enough).

   Run this via bash (chat containers mount host OAuth dirs under `/root/...`):

   ```bash
   # Inside Docker chat/runner:
   GOOGLE_OAUTH_CREDENTIALS="/root/.google-workspace-mcp/credentials.json" \
     npx -y @scottie-will/google-tasks-mcp auth

   # On the host (if not in a container):
   GOOGLE_OAUTH_CREDENTIALS="$HOME/.google-workspace-mcp/credentials.json" \
     npx -y @scottie-will/google-tasks-mcp auth
   ```

   This opens a browser (or prints a URL). Wait until it prints `Authentication successful`.
   If the Google Tasks `authenticate` MCP tool is available in this session, you may use that instead and walk the user through its URL.

5. **Verify before declaring done.** Confirm the token file exists and is non-empty:

   ```bash
   test -s /root/.config/google-tasks-mcp/tokens.json || test -s "$HOME/.config/google-tasks-mcp/tokens.json"
   ```

   If that fails, setup is **not** finished — keep authenticating. Do **not** tell the user they are done while the Connectors UI still shows "Tasks OAuth token missing".

---

## Notion

The Notion connector uses `@notionhq/notion-mcp-server` with a static access token (`NOTION_TOKEN`).

**Default: create a personal access token (PAT).** Only use an internal connection if the user explicitly wants a team-owned bot with pages shared individually.

### Personal access token (default)

1. Go to [Notion Developer portal → Personal access tokens](https://www.notion.so/profile/integrations).
2. Open the **Personal access tokens** tab (not Connections).
3. Click **New token**, name it (e.g. "llm-flows"), and select capabilities:
   - **Read content** — required for agents to read pages and databases
   - **Update content** / **Insert content** — add if the agent should edit Notion
4. Click **Create token** and copy the value immediately (starts with `ntn_`).
5. Print the token for the user to paste into the Notion connector config in the llm-flows UI.

No page-sharing step is needed — the PAT uses the creator's existing Notion permissions.

### Internal connection (only if user explicitly requests a team bot)

1. Go to [Notion Developer portal → Connections](https://www.notion.so/profile/integrations).
2. Create a new **internal connection** (e.g. "llm-flows") for the workspace.
3. Open the connection → **Configuration** tab → copy the **installation access token** (starts with `ntn_`).
4. Share pages/databases with the connection: open each page → **⋯** → **Add connections** → select your connection.
5. Print the token for the user to paste into the Notion connector config in the llm-flows UI.

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
