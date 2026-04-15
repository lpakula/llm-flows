import { useState, useEffect } from "react";
import { api } from "@/api/client";
import type { GatewayConfig } from "@/api/types";

export function GatewayView() {
  const [gateway, setGateway] = useState<GatewayConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [gwEditing, setGwEditing] = useState<Partial<GatewayConfig>>({});
  const [gwSaving, setGwSaving] = useState<string | null>(null);
  const [gwSaved, setGwSaved] = useState<string | null>(null);
  const [newChatId, setNewChatId] = useState("");

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

  const saveGateway = async (key: keyof GatewayConfig, value: unknown) => {
    setGwSaving(key);
    try {
      const updated = await api.updateGatewayConfig({ [key]: value } as Partial<GatewayConfig>);
      setGateway(updated);
      setGwEditing((prev) => { const next = { ...prev }; delete next[key]; return next; });
      setGwSaved(key);
      setTimeout(() => setGwSaved((k) => (k === key ? null : k)), 2000);
    } catch (e) {
      console.error("Failed to save gateway config:", e);
    }
    setGwSaving(null);
  };

  const addChatId = async () => {
    const id = parseInt(newChatId);
    if (isNaN(id)) return;
    const current = gateway?.telegram_allowed_chat_ids || [];
    if (current.includes(id)) return;
    await saveGateway("telegram_allowed_chat_ids", [...current, id]);
    setNewChatId("");
  };

  const removeChatId = async (id: number) => {
    const current = gateway?.telegram_allowed_chat_ids || [];
    await saveGateway("telegram_allowed_chat_ids", current.filter((c) => c !== id));
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-2">Gateway</h2>
      <p className="text-xs text-gray-500 mb-6">
        External notification channels. Restart daemon after changes.
      </p>

      {loading && <div className="text-gray-500">Loading...</div>}

      {!loading && gateway && (
        <div>
          <div className="mb-3">
            <h3 className="text-base font-semibold">Telegram</h3>
            <p className="text-xs text-gray-500 mt-0.5">Receive run notifications and respond to human steps via Telegram</p>
          </div>

          <div className="border border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900/60">
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Setting</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden md:table-cell">Description</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Value</th>
                  <th className="px-4 py-3 w-20"></th>
                </tr>
              </thead>
              <tbody>
                <tr className="bg-gray-900 border-b border-gray-800">
                  <td className="px-4 py-3 font-medium text-white whitespace-nowrap">Enabled</td>
                  <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">Enable Telegram notifications</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => saveGateway("telegram_enabled", !gateway.telegram_enabled)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${gateway.telegram_enabled ? "bg-blue-600" : "bg-gray-700"}`}
                    >
                      <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${gateway.telegram_enabled ? "translate-x-4" : "translate-x-1"}`} />
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {gwSaved === "telegram_enabled" && <span className="text-xs text-green-400">Saved</span>}
                  </td>
                </tr>

                <tr className="bg-gray-900 border-b border-gray-800">
                  <td className="px-4 py-3 font-medium text-white whitespace-nowrap">Bot token</td>
                  <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">Telegram bot API token from @BotFather</td>
                  <td className="px-4 py-3">
                    <input
                      type="password"
                      value={gwEditing.telegram_bot_token ?? gateway.telegram_bot_token}
                      onChange={(e) => setGwEditing((prev) => ({ ...prev, telegram_bot_token: e.target.value }))}
                      onKeyDown={(e) => e.key === "Enter" && gwEditing.telegram_bot_token !== undefined && saveGateway("telegram_bot_token", gwEditing.telegram_bot_token)}
                      placeholder="123456:ABC-DEF..."
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-72 font-mono focus:outline-none focus:border-gray-500"
                    />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {gwSaved === "telegram_bot_token" ? (
                      <span className="text-xs text-green-400">Saved</span>
                    ) : (
                      <button
                        onClick={() => gwEditing.telegram_bot_token !== undefined && saveGateway("telegram_bot_token", gwEditing.telegram_bot_token)}
                        disabled={gwEditing.telegram_bot_token === undefined || gwSaving === "telegram_bot_token"}
                        className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                      >
                        {gwSaving === "telegram_bot_token" ? "Saving…" : "Save"}
                      </button>
                    )}
                  </td>
                </tr>

                <tr className="bg-gray-900">
                  <td className="px-4 py-3 font-medium text-white whitespace-nowrap">Chat IDs</td>
                  <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">Telegram chat IDs allowed to receive notifications (empty = all)</td>
                  <td className="px-4 py-3" colSpan={2}>
                    <div className="flex items-center gap-2 flex-wrap">
                      {(gateway.telegram_allowed_chat_ids || []).map((id) => (
                        <span
                          key={id}
                          className="group inline-flex items-center gap-1 bg-gray-800 border border-gray-700 rounded px-2 py-0.5 font-mono text-xs text-gray-300"
                        >
                          {id}
                          <button
                            onClick={() => removeChatId(id)}
                            className="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity leading-none"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                      <div className="inline-flex items-center gap-1">
                        <input
                          value={newChatId}
                          onChange={(e) => setNewChatId(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && addChatId()}
                          placeholder="Chat ID"
                          className="bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs font-mono w-28 focus:outline-none focus:border-gray-500"
                        />
                        <button
                          onClick={addChatId}
                          disabled={!newChatId.trim() || isNaN(parseInt(newChatId))}
                          className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                        >
                          Add
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
