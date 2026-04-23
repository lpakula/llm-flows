# Connector Setup Guide

How to obtain API keys and tokens for each connector in llm-flows.

## Agent behavior

1. When the user asks to set up a connector, **first check for existing credentials** (see "Reusing existing Google credentials" below).
2. **Always default to browser automation.** Navigate directly to the **external service portal** (e.g. `https://console.cloud.google.com`, `https://github.com/settings/tokens`, etc.) — NOT the llm-flows UI. Follow the steps from the guide below, clicking through the portal pages for the user. When you hit a login/auth screen, tell the user: "Please log in in the browser window, then tell me when you're done." Wait for their reply before continuing.
3. **Do NOT offer manual steps** unless the user explicitly asks for them. You know all the steps — use them to drive the browser. If the user asks "how does this work?" or "show me the steps", then print the relevant section.
4. When you have the keys/tokens, **configure the connector via CLI** — do NOT ask the user to paste values manually. Use these commands:

```bash
llmflows connectors add <server_id>                     # install from catalog (if not already installed)
llmflows connectors config <server_id> <KEY> <value>     # set each credential
llmflows connectors enable <server_id>                   # enable the connector
```

Example for Gmail:
```bash
llmflows connectors add gmail
llmflows connectors config gmail GOOGLE_CLIENT_ID "xxx.apps.googleusercontent.com"
llmflows connectors config gmail GOOGLE_CLIENT_SECRET "GOCSPX-xxx"
llmflows connectors config gmail GOOGLE_REFRESH_TOKEN "1//0xxx"
llmflows connectors enable gmail
```

### Reusing existing Google credentials

All Google connectors (Gmail, Google Drive, Google Calendar, YouTube) share the same **Client ID** and **Client Secret**. Before running the full setup:

1. Run `llmflows connectors list` to see which connectors are already installed.
2. If another Google connector is already configured (e.g. Calendar has credentials and the user wants to add Gmail), **reuse the Client ID and Client Secret** — copy them to the new connector via CLI.
3. The only extra steps the user needs are:
   - **Enable the additional API** in Google Cloud Console (e.g. Gmail API).
   - **Add the new scope** to the OAuth consent screen.
   - **Generate a new Refresh Token** that includes all needed scopes (old + new) via OAuth Playground.
4. Then configure the new connector with the same Client ID / Client Secret and the new Refresh Token.

Example — user already has Google Calendar, wants to add Gmail:
```bash
# Client ID and Secret are the same — copy from the existing connector
llmflows connectors add gmail
llmflows connectors config gmail GOOGLE_CLIENT_ID "<same as calendar>"
llmflows connectors config gmail GOOGLE_CLIENT_SECRET "<same as calendar>"
# Only the Refresh Token needs to be regenerated with the additional gmail scope
llmflows connectors config gmail GOOGLE_REFRESH_TOKEN "<new token with both scopes>"
llmflows connectors enable gmail
```
Also update the Calendar connector's Refresh Token to the new one so both connectors use the same multi-scope token.

---

## Google Services (Gmail, Google Drive, Google Calendar, YouTube)

All Google connectors need three values: **Client ID**, **Client Secret**, and **Refresh Token**.
They all share the same Google Cloud project and OAuth credentials.

> **If another Google connector is already configured**, skip Steps 1–4. You only need to enable the new API (Step 2), add the new scope to the consent screen (Step 3), and generate a new Refresh Token that covers all scopes (Step 5). Then copy the same Client ID and Client Secret to the new connector. See "Reusing existing Google credentials" in Agent behavior above.

### Step 1 — Create a Google Cloud project (first time only)

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
4. Under **Scopes**, add the scopes for **all** Google connectors you want to use:
   - Gmail: `https://www.googleapis.com/auth/gmail.modify`
   - Drive: `https://www.googleapis.com/auth/drive`
   - Calendar: `https://www.googleapis.com/auth/calendar`
   - YouTube: `https://www.googleapis.com/auth/youtube.readonly`
5. Under **Test users**, add your Google account email.

When adding a new Google service later, return here and add the new scope — no need to recreate the consent screen.

### Step 4 — Create OAuth credentials (first time only)

1. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Choose **Web application**.
3. Under **Authorized redirect URIs**, add: `https://developers.google.com/oauthplayground`
4. Copy the **Client ID** and **Client Secret**. These are reused across all Google connectors.

### Step 5 — Get a Refresh Token via OAuth Playground

1. Go to <https://developers.google.com/oauthplayground>.
2. Click the gear icon (top-right) → check **Use your own OAuth credentials**.
3. Enter your Client ID and Client Secret.
4. In the left panel, select the scopes for **all** Google connectors you want to use (not just the new one).
5. Click **Authorize APIs** → sign in with your Google account → grant access.
6. Click **Exchange authorization code for tokens**.
7. Copy the **Refresh Token**.

**Important**: When adding a new scope, you must regenerate the Refresh Token with all scopes selected. Update the token on all existing Google connectors too.

### Step 6 — Configure in llm-flows

Use the CLI to add the connector and set the credentials (see Agent behavior above). If adding a second/third Google connector, copy the Client ID and Client Secret from the existing one and only set the new Refresh Token.

---

## Notion

1. Go to <https://www.notion.so/my-integrations>.
2. Click **New integration**.
3. Name it (e.g. "llm-flows"), select the workspace, and click **Submit**.
4. Copy the **Internal Integration Secret** (starts with `ntn_`).
5. In Notion, open the pages/databases you want the integration to access → click **⋯** → **Connect to** → select your integration.
6. Configure via CLI: `llmflows connectors add notion && llmflows connectors config notion NOTION_API_KEY "ntn_xxx" && llmflows connectors enable notion`

---

## GitHub

1. Go to <https://github.com/settings/tokens?type=beta> (Fine-grained tokens) or <https://github.com/settings/tokens> (Classic).
2. Click **Generate new token**.
3. For fine-grained tokens: select the repositories and permissions you need.
   For classic tokens: select scopes like `repo`, `read:org` as needed.
4. Copy the token.
5. Configure via CLI: `llmflows connectors add github && llmflows connectors config github GITHUB_TOKEN "ghp_xxx" && llmflows connectors enable github`

---

## Slack

1. Go to <https://api.slack.com/apps> and click **Create New App → From scratch**.
2. Name it (e.g. "llm-flows") and select your workspace.
3. Under **OAuth & Permissions**, add the Bot Token Scopes you need (e.g. `channels:read`, `chat:write`, `users:read`).
4. Click **Install to Workspace** and authorize.
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`).
6. Configure via CLI: `llmflows connectors add slack && llmflows connectors config slack SLACK_BOT_TOKEN "xoxb-xxx" && llmflows connectors enable slack`

---

## Linear

1. Go to <https://linear.app/settings/api>.
2. Under **Personal API keys**, click **Create key**.
3. Copy the key.
4. Configure via CLI: `llmflows connectors add linear && llmflows connectors config linear LINEAR_API_KEY "lin_api_xxx" && llmflows connectors enable linear`

---

## PostgreSQL

No external setup needed — just provide your connection string.

Format: `postgresql://user:password@host:port/database`

Configure via CLI: `llmflows connectors add postgres && llmflows connectors config postgres DATABASE_URL "postgresql://..." && llmflows connectors enable postgres`
