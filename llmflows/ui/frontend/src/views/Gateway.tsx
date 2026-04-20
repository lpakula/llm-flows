import { useState, useEffect } from "react";
import { api } from "@/api/client";
import type { GatewayConfig } from "@/api/types";
import { ChevronRight } from "lucide-react";

type ChannelDef = {
  id: string;
  name: string;
  description: string;
  enabledKey: keyof GatewayConfig;
  fields: {
    key: keyof GatewayConfig;
    label: string;
    type: "secret" | "tags-number" | "tags-string";
    placeholder: string;
    description: string;
  }[];
};

const CHANNELS: ChannelDef[] = [
  {
    id: "telegram",
    name: "Telegram",
    description: "Receive run notifications and respond to human steps via Telegram",
    enabledKey: "telegram_enabled",
    fields: [
      { key: "telegram_bot_token", label: "Bot token", type: "secret", placeholder: "123456:ABC-DEF...", description: "Telegram bot API token from @BotFather" },
      { key: "telegram_allowed_chat_ids", label: "Chat IDs", type: "tags-number", placeholder: "Chat ID", description: "Allowed chat IDs (empty = all)" },
    ],
  },
  {
    id: "slack",
    name: "Slack",
    description: "Receive run notifications and respond to human steps via Slack (Socket Mode)",
    enabledKey: "slack_enabled",
    fields: [
      { key: "slack_bot_token", label: "Bot token", type: "secret", placeholder: "xoxb-...", description: "Slack Bot User OAuth Token" },
      { key: "slack_app_token", label: "App token", type: "secret", placeholder: "xapp-...", description: "Slack App-Level Token for Socket Mode" },
      { key: "slack_allowed_channel_ids", label: "Channel IDs", type: "tags-string", placeholder: "C0123456789", description: "Allowed channel IDs (empty = all)" },
    ],
  },
];

function ChannelCard({
  channel,
  gateway,
  onSave,
}: {
  channel: ChannelDef;
  gateway: GatewayConfig;
  onSave: (key: keyof GatewayConfig, value: unknown) => Promise<void>;
}) {
  const [editing, setEditing] = useState<Partial<GatewayConfig>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [newTag, setNewTag] = useState("");
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const enabled = gateway[channel.enabledKey] as boolean;

  const toggleEnabled = async () => {
    setTogglingEnabled(true);
    await onSave(channel.enabledKey, !enabled);
    if (!enabled) setExpanded(true);
    setTogglingEnabled(false);
  };

  const saveField = async (key: keyof GatewayConfig, value: unknown) => {
    setSaving(key);
    await onSave(key, value);
    setEditing((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setSaved(key);
    setTimeout(() => setSaved((k) => (k === key ? null : k)), 2000);
    setSaving(null);
  };

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 overflow-hidden">
      <div
        className="flex items-center justify-between p-4 cursor-pointer"
        onClick={() => enabled && setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {enabled && (
            <ChevronRight size={14} className={`text-gray-500 transition-transform flex-shrink-0 ${expanded ? "rotate-90" : ""}`} />
          )}
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-white">{channel.name}</h3>
            <p className="text-xs text-gray-500 mt-0.5">{channel.description}</p>
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); toggleEnabled(); }}
          disabled={togglingEnabled}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0 ml-4 ${
            enabled ? "bg-blue-500" : "bg-gray-700"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              enabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>

      {enabled && expanded && (
        <div className="border-t border-gray-800 p-4 space-y-4">
          {channel.fields.map((field) => (
            <div key={field.key}>
              <label className="text-xs font-medium text-gray-400 mb-1.5 block">
                {field.label}
                <span className="font-normal text-gray-600 ml-2">{field.description}</span>
              </label>

              {field.type === "secret" && (
                <div className="flex items-center gap-2">
                  <input
                    type="password"
                    value={(editing[field.key] as string | undefined) ?? (gateway[field.key] as string)}
                    onChange={(e) => setEditing((prev) => ({ ...prev, [field.key]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && editing[field.key] !== undefined && saveField(field.key, editing[field.key])}
                    placeholder={field.placeholder}
                    className="bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-sm w-72 font-mono focus:outline-none focus:border-gray-500"
                  />
                  {saved === field.key ? (
                    <span className="text-xs text-green-400">Saved</span>
                  ) : (
                    <button
                      onClick={() => editing[field.key] !== undefined && saveField(field.key, editing[field.key])}
                      disabled={editing[field.key] === undefined || saving === field.key}
                      className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                    >
                      {saving === field.key ? "Saving…" : "Save"}
                    </button>
                  )}
                </div>
              )}

              {(field.type === "tags-number" || field.type === "tags-string") && (
                <div className="flex items-center gap-2 flex-wrap">
                  {(gateway[field.key] as (string | number)[])?.map((id) => (
                    <span
                      key={String(id)}
                      className="group inline-flex items-center gap-1 bg-gray-800 border border-gray-700 rounded px-2 py-0.5 font-mono text-xs text-gray-300"
                    >
                      {String(id)}
                      <button
                        onClick={() => {
                          const current = gateway[field.key] as (string | number)[];
                          onSave(field.key, current.filter((c) => c !== id));
                        }}
                        className="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity leading-none"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  <div className="inline-flex items-center gap-1">
                    <input
                      value={newTag}
                      onChange={(e) => setNewTag(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key !== "Enter") return;
                        const current = (gateway[field.key] as (string | number)[]) || [];
                        if (field.type === "tags-number") {
                          const num = parseInt(newTag);
                          if (isNaN(num) || current.includes(num)) return;
                          onSave(field.key, [...current, num]);
                        } else {
                          const val = newTag.trim();
                          if (!val || current.includes(val)) return;
                          onSave(field.key, [...current, val]);
                        }
                        setNewTag("");
                      }}
                      placeholder={field.placeholder}
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs font-mono w-28 focus:outline-none focus:border-gray-500"
                    />
                    <button
                      onClick={() => {
                        const current = (gateway[field.key] as (string | number)[]) || [];
                        if (field.type === "tags-number") {
                          const num = parseInt(newTag);
                          if (isNaN(num) || current.includes(num)) return;
                          onSave(field.key, [...current, num]);
                        } else {
                          const val = newTag.trim();
                          if (!val || current.includes(val)) return;
                          onSave(field.key, [...current, val]);
                        }
                        setNewTag("");
                      }}
                      disabled={!newTag.trim() || (field.type === "tags-number" && isNaN(parseInt(newTag)))}
                      className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                    >
                      Add
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function GatewayView() {
  const [gateway, setGateway] = useState<GatewayConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        setGateway(await api.getGatewayConfig());
      } catch (e) {
        console.error("Failed to load gateway config:", e);
      }
      setLoading(false);
    })();
  }, []);

  const handleSave = async (key: keyof GatewayConfig, value: unknown) => {
    try {
      const updated = await api.updateGatewayConfig({ [key]: value } as Partial<GatewayConfig>);
      setGateway(updated);
    } catch (e) {
      console.error("Failed to save gateway config:", e);
    }
  };

  const handleRestart = async () => {
    setRestarting(true);
    try {
      await api.restartGateway();
    } catch (e) {
      console.error("Failed to restart gateway:", e);
    }
    setTimeout(() => setRestarting(false), 2000);
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xl font-semibold">Gateway</h2>
        <button
          onClick={handleRestart}
          disabled={restarting}
          className="text-xs px-3 py-1.5 rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 disabled:opacity-40 transition-colors"
        >
          {restarting ? "Restarting…" : "Restart Gateway"}
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-6">
        Enable channels to receive notifications and control flows remotely. Click "Restart Gateway" after changes.
      </p>

      {loading && <div className="text-gray-500">Loading...</div>}

      {!loading && gateway && (
        <div>
          <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Channels</h3>
          <div className="space-y-3">
            {CHANNELS.map((ch) => (
              <ChannelCard key={ch.id} channel={ch} gateway={gateway} onSave={handleSave} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
