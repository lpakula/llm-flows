---
name: llmflows-connectors
description: Set up and configure connectors (Gmail, Google Drive, Calendar, YouTube, Notion, GitHub, Slack, Linear, Postgres). Use when the user wants to connect a service, configure OAuth, add API keys, or troubleshoot a connector.
---

# Connector Setup Guide

How to obtain API keys and tokens for each connector in llm-flows.

## Agent behavior

1. When the user asks to set up a connector, **first check for existing credentials** (see "Reusing existing Google credentials" below).
2. **Always default to browser automation.** Navigate directly to the **external service portal** — NOT the llm-flows UI. Follow the steps from the guide below, clicking through the portal pages for the user. When you hit a login/auth screen, tell the user: "Please log in in the browser window, then tell me when you're done." Wait for their reply before continuing.
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

### Scopes reference

| Connector        | API to enable          | OAuth scope                                              |
|------------------|------------------------|----------------------------------------------------------|
| Gmail            | Gmail API              | `https://www.googleapis.com/auth/gmail.modify`           |
| Google Drive     | Google Drive API       | `https://www.googleapis.com/auth/drive`                  |
| Google Calendar  | Google Calendar API    | `https://www.googleapis.com/auth/calendar`               |
| YouTube          | YouTube Data API v3    | `https://www.googleapis.com/auth/youtube.readonly`       |

### Step 1 — Create a Google Cloud project (first time only)

Navigate directly to: `https://console.cloud.google.com/projectcreate`

1. Set the project name to "llm-flows" (or any name the user prefers).
2. Click **Create**.
3. **Wait 5–10 seconds** for the project to be created. The page may redirect, or a notification will appear.
4. After creation, note the **project ID** (shown on the page or in the notification). You'll use it in all subsequent URLs.

**Browser automation tip**: After project creation, navigate directly to the next step URL with `?project=PROJECT_ID` to avoid needing to use the project selector dropdown.

### Step 2 — Enable APIs

Navigate directly to the API page for the connector you need. Use these direct URLs (replace `PROJECT_ID` with the actual project ID):

| Connector        | Direct URL                                                                       |
|------------------|----------------------------------------------------------------------------------|
| Gmail            | `https://console.cloud.google.com/apis/library/gmail.googleapis.com?project=PROJECT_ID`             |
| Google Drive     | `https://console.cloud.google.com/apis/library/drive.googleapis.com?project=PROJECT_ID`             |
| Google Calendar  | `https://console.cloud.google.com/apis/library/calendar-json.googleapis.com?project=PROJECT_ID`     |
| YouTube          | `https://console.cloud.google.com/apis/library/youtube.googleapis.com?project=PROJECT_ID`           |

Click the **Enable** button on the API page.

**Browser automation tip**: If the page asks you to select a project first, navigate to `https://console.cloud.google.com/welcome?project=PROJECT_ID` first, then retry the API URL.

### Step 3 — Configure OAuth consent screen

Navigate directly to: `https://console.cloud.google.com/auth/overview?project=PROJECT_ID`

If this is the first time setting up OAuth for this project, you'll see a "Get started" or "Configure consent screen" button. Click it.

1. **App name**: "llm-flows" (or whatever the user prefers)
2. **User support email**: select the user's email from the dropdown
3. **Audience / User type**: choose **External** (or Internal if using Google Workspace)
4. **Developer contact email**: enter the user's email
5. Click through to save the basic settings.

#### Add scopes

Navigate to: `https://console.cloud.google.com/auth/scopes?project=PROJECT_ID`

Or from the consent screen page, find the "Data Access" or "Scopes" section.

1. Click **Add or remove scopes**
2. Search for and add the scope(s) from the scopes reference table above
3. If the scope doesn't appear in the search results, use **Manually add scopes** — paste the scope URL directly (e.g. `https://www.googleapis.com/auth/gmail.modify`)
4. Save changes

#### Add test users

Navigate to: `https://console.cloud.google.com/auth/audience?project=PROJECT_ID`

Since the app is in "Testing" mode (not published), only listed test users can authorize:
1. Click **Add users**
2. Add the user's Google account email
3. Save

### Step 4 — Create OAuth credentials (first time only)

Navigate directly to: `https://console.cloud.google.com/apis/credentials/oauthclient?project=PROJECT_ID`

1. **Application type**: select **Web application**
2. **Name**: "llm-flows" (or leave default)
3. Under **Authorized redirect URIs**, click **Add URI** and enter: `https://developers.google.com/oauthplayground`
4. Click **Create**
5. A dialog will show the **Client ID** and **Client Secret** — copy both. These are reused across all Google connectors.

**Save these values** — you'll need them for the next step and for CLI configuration.

### Step 5 — Get a Refresh Token

You have two options: OAuth Playground (browser) or curl (command line). The curl method is more reliable for automation.

#### Option A: curl (recommended for agents)

Build and run the authorization URL in the browser, then exchange the code via curl.

1. Navigate the browser to this URL (replace CLIENT_ID and SCOPE):
```
https://accounts.google.com/o/oauth2/v2/auth?client_id=CLIENT_ID&redirect_uri=https://developers.google.com/oauthplayground&response_type=code&scope=SCOPE&access_type=offline&prompt=consent
```

For SCOPE, use the scope from the reference table. For multiple scopes, join them with `+` (URL-encoded space).

Example for Gmail:
```
https://accounts.google.com/o/oauth2/v2/auth?client_id=XXX.apps.googleusercontent.com&redirect_uri=https://developers.google.com/oauthplayground&response_type=code&scope=https://www.googleapis.com/auth/gmail.modify&access_type=offline&prompt=consent
```

2. The user signs in and grants access. The browser redirects to `https://developers.google.com/oauthplayground?code=AUTH_CODE_HERE`.
3. Grab the `code` parameter from the URL. Take a browser snapshot to read the redirect URL.
4. Exchange the code for a refresh token via shell:

```bash
curl -s -X POST https://oauth2.googleapis.com/token \
  -d "code=AUTH_CODE" \
  -d "client_id=CLIENT_ID" \
  -d "client_secret=CLIENT_SECRET" \
  -d "redirect_uri=https://developers.google.com/oauthplayground" \
  -d "grant_type=authorization_code" | python3 -c "import sys,json; print(json.load(sys.stdin)['refresh_token'])"
```

This prints just the refresh token.

#### Option B: OAuth Playground (browser)

Navigate to: `https://developers.google.com/oauthplayground`

1. Click the **gear icon** (⚙️) in the top-right corner
2. Check **Use your own OAuth credentials**
3. Enter the Client ID and Client Secret from Step 4
4. Close the settings panel
5. In the left panel "Step 1", find or type the scope URL (e.g. `https://www.googleapis.com/auth/gmail.modify`)
6. Click **Authorize APIs** → sign in → grant access
7. In "Step 2", click **Exchange authorization code for tokens**
8. Copy the **Refresh Token** from the response

**Important**: When adding a new scope later, regenerate the Refresh Token with ALL scopes selected (old + new). Update the token on all existing Google connectors.

### Step 6 — Configure in llm-flows

Use the CLI to add the connector and set the credentials (see Agent behavior above). If adding a second/third Google connector, copy the Client ID and Client Secret from the existing one and only set the new Refresh Token.

---

## Notion

1. Go to `https://www.notion.so/my-integrations`.
2. Click **New integration**.
3. Name it (e.g. "llm-flows"), select the workspace, and click **Submit**.
4. Copy the **Internal Integration Secret** (starts with `ntn_`).
5. In Notion, open the pages/databases you want the integration to access → click **⋯** → **Connect to** → select your integration.
6. Configure via CLI: `llmflows connectors add notion && llmflows connectors config notion NOTION_API_KEY "ntn_xxx" && llmflows connectors enable notion`

---

## GitHub

1. Go to `https://github.com/settings/tokens?type=beta` (Fine-grained tokens) or `https://github.com/settings/tokens` (Classic).
2. Click **Generate new token**.
3. For fine-grained tokens: select the repositories and permissions you need.
   For classic tokens: select scopes like `repo`, `read:org` as needed.
4. Copy the token.
5. Configure via CLI: `llmflows connectors add github && llmflows connectors config github GITHUB_TOKEN "ghp_xxx" && llmflows connectors enable github`

---

## Slack

1. Go to `https://api.slack.com/apps` and click **Create New App → From scratch**.
2. Name it (e.g. "llm-flows") and select your workspace.
3. Under **OAuth & Permissions**, add the Bot Token Scopes you need (e.g. `channels:read`, `chat:write`, `users:read`).
4. Click **Install to Workspace** and authorize.
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`).
6. Configure via CLI: `llmflows connectors add slack && llmflows connectors config slack SLACK_BOT_TOKEN "xoxb-xxx" && llmflows connectors enable slack`

---

## Linear

1. Go to `https://linear.app/settings/api`.
2. Under **Personal API keys**, click **Create key**.
3. Copy the key.
4. Configure via CLI: `llmflows connectors add linear && llmflows connectors config linear LINEAR_API_KEY "lin_api_xxx" && llmflows connectors enable linear`

---

## PostgreSQL

No external setup needed — just provide your connection string.

Format: `postgresql://user:password@host:port/database`

Configure via CLI: `llmflows connectors add postgres && llmflows connectors config postgres DATABASE_URL "postgresql://..." && llmflows connectors enable postgres`
