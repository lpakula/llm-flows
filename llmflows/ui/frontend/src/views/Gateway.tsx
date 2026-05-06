import { useState, useEffect, useRef } from "react";
import { api } from "@/api/client";
import type { GatewayConfig } from "@/api/types";
import { X } from "lucide-react";

type ChannelFieldDef = {
  key: keyof GatewayConfig;
  label: string;
  type: "secret" | "tags-number" | "tags-string";
  placeholder: string;
  description: string;
};

type ChannelDef = {
  id: string;
  name: string;
  description: string;
  enabledKey: keyof GatewayConfig;
  fields: ChannelFieldDef[];
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

/* ---------- Modal shell ---------- */

function Modal({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  const backdropRef = useRef<HTMLDivElement>(null);
  if (!open) return null;
  return (
    <div ref={backdropRef} className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-gray-900 border border-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto">
        {children}
      </div>
    </div>
  );
}

/* ---------- Channel config modal ---------- */

function ChannelConfigModal({
  channel,
  gateway,
  open,
  onClose,
  onSave,
}: {
  channel: ChannelDef;
  gateway: GatewayConfig;
  open: boolean;
  onClose: () => void;
  onSave: (key: keyof GatewayConfig, value: unknown) => Promise<void>;
}) {
  const [editing, setEditing] = useState<Partial<GatewayConfig>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [newTag, setNewTag] = useState("");
  const [togglingEnabled, setTogglingEnabled] = useState(false);

  const enabled = gateway[channel.enabledKey] as boolean;

  const toggleEnabled = async () => {
    setTogglingEnabled(true);
    await onSave(channel.enabledKey, !enabled);
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
    <Modal open={open} onClose={onClose}>
      <div className="p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{channel.name}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 p-1"><X size={16} /></button>
        </div>

        <p className="text-sm text-gray-500">{channel.description}</p>

        {/* Enable / Disable toggle */}
        <div className="flex items-center justify-between py-2">
          <span className="text-sm text-gray-300">{enabled ? "Enabled" : "Disabled"}</span>
          <button
            onClick={toggleEnabled}
            disabled={togglingEnabled}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0 ${
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

        {/* Configuration fields */}
        {channel.fields.length > 0 && (
          <div className="space-y-4">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider">Configuration</h3>
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
                      className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-full font-mono focus:outline-none focus:border-gray-500"
                    />
                    {saved === field.key ? (
                      <span className="text-xs text-green-400 whitespace-nowrap">Saved</span>
                    ) : (
                      <button
                        onClick={() => editing[field.key] !== undefined && saveField(field.key, editing[field.key])}
                        disabled={editing[field.key] === undefined || saving === field.key}
                        className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors whitespace-nowrap"
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

        {/* Footer */}
        <div className="flex justify-end pt-2 border-t border-gray-800">
          <button onClick={onClose}
            className="px-4 py-2 text-xs font-medium rounded-lg bg-gray-800 text-white hover:bg-gray-700 transition-colors">
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}

/* ---------- Channel card ---------- */

function ChannelCard({
  channel,
  gateway,
  onClick,
}: {
  channel: ChannelDef;
  gateway: GatewayConfig;
  onClick: () => void;
}) {
  const enabled = gateway[channel.enabledKey] as boolean;

  return (
    <div
      onClick={onClick}
      className="text-left rounded-xl border border-gray-800 bg-gray-900 hover:border-gray-600 transition-colors p-5 flex items-center gap-4 cursor-pointer"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full shrink-0 ${enabled ? "bg-green-400" : "bg-gray-600"}`} />
          <span className="text-sm font-medium text-white truncate">{channel.name}</span>
        </div>
        <span className="text-[11px] text-gray-500 block truncate">{channel.description}</span>
      </div>
      <div className="shrink-0">
        <span className={`text-[11px] font-medium px-3 py-1 rounded-lg ${
          enabled
            ? "text-green-400 bg-green-400/10 border border-green-400/20"
            : "text-gray-500 bg-gray-800 border border-gray-700"
        }`}>
          {enabled ? "Enabled" : "Disabled"}
        </span>
      </div>
    </div>
  );
}

/* ---------- Main view ---------- */

export function GatewayView() {
  const [gateway, setGateway] = useState<GatewayConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [restarting, setRestarting] = useState(false);
  const [modalChannel, setModalChannel] = useState<ChannelDef | null>(null);

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

  const enabledChannels = gateway ? CHANNELS.filter((ch) => gateway[ch.enabledKey] as boolean) : [];
  const disabledChannels = gateway ? CHANNELS.filter((ch) => !(gateway[ch.enabledKey] as boolean)) : [];

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="space-y-8">
        <div>
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-xl font-semibold">Gateway</h2>
            <button
              onClick={handleRestart}
              disabled={restarting}
              className="text-xs px-3 py-1.5 rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 disabled:opacity-40 transition-colors"
            >
              {restarting ? "Restarting…" : "Restart Gateway"}
            </button>
          </div>
          <p className="text-xs text-gray-500">
            Enable channels to receive notifications and control flows remotely. Click a channel to configure it.
          </p>
        </div>

        {loading && <div className="text-gray-500">Loading...</div>}

        {!loading && gateway && (
          <>
            {enabledChannels.length > 0 && (
              <section>
                <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-3">Enabled</h3>
                <div className="grid grid-cols-3 gap-4">
                  {enabledChannels.map((ch) => (
                    <ChannelCard key={ch.id} channel={ch} gateway={gateway} onClick={() => setModalChannel(ch)} />
                  ))}
                </div>
              </section>
            )}

            {disabledChannels.length > 0 && (
              <section>
                <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-3">Not Enabled</h3>
                <div className="grid grid-cols-3 gap-4">
                  {disabledChannels.map((ch) => (
                    <ChannelCard key={ch.id} channel={ch} gateway={gateway} onClick={() => setModalChannel(ch)} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>

      {modalChannel && gateway && (
        <ChannelConfigModal
          channel={modalChannel}
          gateway={gateway}
          open={!!modalChannel}
          onClose={() => setModalChannel(null)}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
