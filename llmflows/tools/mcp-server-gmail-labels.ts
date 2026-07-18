/**
 * MCP server: Gmail label helpers (remove_label / archive).
 *
 * Companion to the Google Workspace connector. Reuses OAuth tokens from
 * ~/.google-workspace-mcp/ (same credentials used by @alanxchen/google-workspace-mcp).
 *
 * Tools:
 *   remove_label  – remove a label from a message (e.g. INBOX, UNREAD, STARRED)
 *   archive_email – archive one or more messages (remove INBOX label)
 */

import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const CONFIG_DIR =
  process.env.GOOGLE_WORKSPACE_MCP_DIR ||
  path.join(os.homedir(), ".google-workspace-mcp");
const TOKEN_PATH = path.join(CONFIG_DIR, "token.json");
const CREDENTIALS_PATH = path.join(CONFIG_DIR, "credentials.json");

type TokenData = {
  access_token?: string;
  refresh_token?: string;
  expiry_date?: number;
  token_type?: string;
  scope?: string;
};

type OAuthClientConfig = {
  client_id: string;
  client_secret: string;
};

async function loadJson<T>(filePath: string): Promise<T | null> {
  try {
    const content = await fs.readFile(filePath, "utf-8");
    return JSON.parse(content) as T;
  } catch {
    return null;
  }
}

async function saveToken(token: TokenData): Promise<void> {
  await fs.mkdir(CONFIG_DIR, { recursive: true });
  await fs.writeFile(TOKEN_PATH, JSON.stringify(token, null, 2));
}

function getOAuthClientConfig(credentials: Record<string, unknown>): OAuthClientConfig {
  const creds = (credentials.installed || credentials.web) as OAuthClientConfig | undefined;
  if (!creds?.client_id || !creds?.client_secret) {
    throw new Error(`Invalid OAuth credentials at ${CREDENTIALS_PATH}`);
  }
  return creds;
}

async function refreshAccessToken(token: TokenData): Promise<string> {
  const credentials = await loadJson<Record<string, unknown>>(CREDENTIALS_PATH);
  if (!credentials) {
    throw new Error(
      `Google Workspace credentials not found at ${CREDENTIALS_PATH}. ` +
        "Connect and authenticate the Google Workspace connector first."
    );
  }
  if (!token.refresh_token) {
    throw new Error(
      "Google Workspace token has no refresh_token. Re-authenticate the Google Workspace connector."
    );
  }

  const creds = getOAuthClientConfig(credentials);
  const resp = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: creds.client_id,
      client_secret: creds.client_secret,
      refresh_token: token.refresh_token,
      grant_type: "refresh_token",
    }),
  });
  const data = (await resp.json()) as {
    access_token?: string;
    expires_in?: number;
    error?: string;
    error_description?: string;
  };
  if (!resp.ok || !data.access_token) {
    throw new Error(
      data.error_description || data.error || `Token refresh failed (HTTP ${resp.status})`
    );
  }

  const updated: TokenData = {
    ...token,
    access_token: data.access_token,
    expiry_date: data.expires_in ? Date.now() + data.expires_in * 1000 : undefined,
  };
  await saveToken(updated);
  return data.access_token;
}

async function getAccessToken(): Promise<string> {
  const token = await loadJson<TokenData>(TOKEN_PATH);
  if (!token) {
    throw new Error(
      `Google Workspace token not found at ${TOKEN_PATH}. ` +
        "Connect and authenticate the Google Workspace connector first."
    );
  }

  const stillValid =
    !!token.access_token &&
    !!token.expiry_date &&
    Date.now() < token.expiry_date - 60_000;

  if (stillValid && token.access_token) {
    return token.access_token;
  }

  return refreshAccessToken(token);
}

async function gmailModify(
  messageId: string,
  body: { addLabelIds?: string[]; removeLabelIds?: string[] }
): Promise<unknown> {
  const accessToken = await getAccessToken();
  const resp = await fetch(
    `https://gmail.googleapis.com/gmail/v1/users/me/messages/${encodeURIComponent(messageId)}/modify`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    }
  );
  const data = await resp.json();
  if (!resp.ok) {
    const err = data as { error?: { message?: string } };
    throw new Error(err.error?.message || `Gmail modify failed (HTTP ${resp.status})`);
  }
  return data;
}

async function gmailBatchModify(
  ids: string[],
  body: { addLabelIds?: string[]; removeLabelIds?: string[] }
): Promise<void> {
  const accessToken = await getAccessToken();
  const resp = await fetch(
    "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ids, ...body }),
    }
  );
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const data = (await resp.json()) as { error?: { message?: string } };
      detail = data.error?.message || detail;
    } catch {
      // ignore
    }
    throw new Error(`Gmail batchModify failed: ${detail}`);
  }
}

function asStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(String).map((s) => s.trim()).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

const server = new Server(
  { name: "llmflows-gmail-labels", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "remove_label",
      description:
        "Remove a Gmail label from a message. Use label ID (e.g. INBOX, UNREAD, STARRED), not the display name. " +
        "Archiving is remove_label with labelId=INBOX (or use archive_email).",
      inputSchema: {
        type: "object" as const,
        properties: {
          messageId: { type: "string", description: "Gmail message ID" },
          labelId: {
            type: "string",
            description: "Label ID to remove (e.g. INBOX, UNREAD, STARRED)",
          },
        },
        required: ["messageId", "labelId"],
      },
    },
    {
      name: "archive_email",
      description:
        "Archive one or more Gmail messages by removing the INBOX label. " +
        "Messages stay in All Mail; they are not trashed.",
      inputSchema: {
        type: "object" as const,
        properties: {
          messageId: {
            type: "string",
            description: "Single Gmail message ID to archive",
          },
          messageIds: {
            type: "array",
            items: { type: "string" },
            description: "Multiple Gmail message IDs to archive in one call",
          },
        },
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "remove_label": {
        const messageId = String((args as any).messageId || "").trim();
        const labelId = String((args as any).labelId || "").trim();
        if (!messageId || !labelId) {
          throw new Error("messageId and labelId are required");
        }
        const result = await gmailModify(messageId, { removeLabelIds: [labelId] });
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(
                { id: messageId, labelId, status: "label_removed", result },
                null,
                2
              ),
            },
          ],
        };
      }
      case "archive_email": {
        const ids = [
          ...asStringArray((args as any).messageId),
          ...asStringArray((args as any).messageIds),
        ];
        const unique = [...new Set(ids)];
        if (!unique.length) {
          throw new Error("Provide messageId or messageIds");
        }
        if (unique.length === 1) {
          await gmailModify(unique[0], { removeLabelIds: ["INBOX"] });
        } else {
          await gmailBatchModify(unique, { removeLabelIds: ["INBOX"] });
        }
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(
                { ids: unique, count: unique.length, status: "archived" },
                null,
                2
              ),
            },
          ],
        };
      }
      default:
        return {
          content: [{ type: "text", text: `Unknown tool: ${name}` }],
          isError: true,
        };
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
});

(async () => {
  const transport = new StdioServerTransport();
  await server.connect(transport);
})();
