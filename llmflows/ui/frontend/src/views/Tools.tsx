import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import type { ConnectorConfig, ConnectorConfigField, CatalogEntry } from "@/api/types";
import { AlertCircle, MessageCircle, X } from "lucide-react";

const BUILTIN_IDS = new Set(["browser", "web_search"]);

function sid(c: ConnectorConfig) { return c.server_id || c.id; }

type InfoEntry = { text: string; status: "ok" | "error" };

type UnifiedItem = {
  id: string;
  name: string;
  description: string;
  connected: boolean;
  installed: boolean;
  connector?: ConnectorConfig;
  catalogEntry?: CatalogEntry;
  info?: InfoEntry[];
};

function buildItems(connectors: ConnectorConfig[], catalog: CatalogEntry[]): UnifiedItem[] {
  const installedIds = new Set(connectors.map((c) => sid(c)));
  const catalogByServerId = new Map(catalog.map((e) => [e.server_id, e]));
  const items: UnifiedItem[] = [];
  for (const c of connectors) {
    const catInfo = catalogByServerId.get(sid(c))?.info;
    items.push({
      id: sid(c), name: c.name, description: c.description,
      connected: c.enabled,
      installed: true, connector: c,
      info: c.info ?? catInfo,
    });
  }
  for (const entry of catalog) {
    if (installedIds.has(entry.server_id)) continue;
    items.push({
      id: entry.server_id, name: entry.name, description: entry.description,
      connected: false,
      installed: false, catalogEntry: entry,
      info: entry.info,
    });
  }
  return items;
}

/* ---------- Modal shell ---------- */

function Modal({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  const backdropRef = useRef<HTMLDivElement>(null);
  if (!open) return null;
  return (
    <div ref={backdropRef} className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
>
      <div className="bg-gray-900 border border-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto">
        {children}
      </div>
    </div>
  );
}

/* ---------- Config modal ---------- */

function ConfigModal({
  connector, open, onClose, onUpdate, isConnected, onAskChat,
}: {
  connector: ConnectorConfig; open: boolean; onClose: () => void;
  onUpdate: (c: ConnectorConfig) => void;
  isConnected?: boolean;
  onAskChat?: (prompt: string) => void;
}) {
  const [localConfig, setLocalConfig] = useState<Record<string, string>>(connector.config);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const googleIds = new Set(["google_workspace", "youtube"]);
  const isGoogle = googleIds.has(sid(connector));

  const connectorId = sid(connector);
  useEffect(() => {
    setLocalConfig(connector.config);
    setDirty(false); setSaved(false); setShowErrors(false);
  }, [connectorId]);

  const setField = (key: string, value: string) => {
    setLocalConfig((prev) => ({ ...prev, [key]: value }));
    setDirty(true); setShowErrors(false);
  };

  const isTopLevel = (f: ConnectorConfigField) => !f.show_when;
  const inlineFields = (sk: string, ov: string) =>
    connector.config_fields.filter((f) => f.show_when && f.show_when[sk] === ov);

  const hasInvalid = () => {
    for (const f of connector.config_fields) {
      if (!f.show_when) continue;
      const vis = Object.entries(f.show_when).every(([k, v]) => localConfig[k] === v);
      if (vis && (f.type === "secret" || f.type === "text") && !localConfig[f.key]?.trim()) return true;
    }
    return false;
  };

  const requiredKeys = new Set(connector.required_credentials ?? []);
  const missingRequired = connector.config_fields
    .filter((f) => requiredKeys.has(f.key))
    .some((f) => !localConfig[f.key]?.trim());

  const hasWarnings = connector.info?.some((i) => i.status === "error") ?? false;

  const saveConfig = async () => {
    if (hasInvalid()) { setShowErrors(true); return; }
    setShowErrors(false); setSaving(true);
    try {
      const updated = await api.updateConnector(sid(connector), { config: localConfig, enabled: true });
      onUpdate(updated);
      onClose();
    } catch (e) { console.error("Failed to save:", e); }
    setSaving(false);
  };

  const doDisconnect = async () => {
    setDisconnecting(true);
    try {
      const emptyConfig: Record<string, string> = {};
      for (const f of connector.config_fields) emptyConfig[f.key] = "";
      const updated = await api.updateConnector(sid(connector), { config: emptyConfig, enabled: false });
      setLocalConfig(emptyConfig);
      onUpdate(updated);
      onClose();
    } catch (e) { console.error("Disconnect failed:", e); }
    setDisconnecting(false);
  };

  return (
    <Modal open={open} onClose={onClose}>
      <div className="p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{connector.name}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 p-1"><X size={16} /></button>
        </div>

        <p className="text-sm text-gray-500">{connector.description}</p>

        {connector.info && connector.info.length > 0 && (
          <div className="space-y-1.5">
            {connector.info.map((item, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full shrink-0 ${item.status === "ok" ? "bg-green-400" : "bg-red-400"}`} />
                <span className={`text-[11px] font-mono ${item.status === "ok" ? "text-gray-500" : "text-red-400/80"}`}>{item.text}</span>
              </div>
            ))}
          </div>
        )}

        {connector.config_fields.length > 0 && (
          <div className="space-y-4">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider">Configuration</h3>
            {connector.config_fields.filter(isTopLevel).map((field) => (
              <div key={field.key}>
                <label className="text-xs font-medium text-gray-400 mb-1.5 block">{field.label}</label>
                {field.type === "select" ? (
                  <SelectField field={field} localConfig={localConfig} setField={setField}
                    inlineFields={inlineFields} showErrors={showErrors}
                    hasInvalid={hasInvalid} saveConfig={saveConfig} />
                ) : (
                  <input type={field.type === "secret" ? "password" : "text"}
                    value={localConfig[field.key] ?? ""}
                    onChange={(e) => setField(field.key, e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !hasInvalid() && saveConfig()}
                    placeholder={field.placeholder}
                    className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-full font-mono focus:outline-none focus:border-gray-500" />
                )}
              </div>
            ))}
          </div>
        )}

        {!isConnected && onAskChat && (
          <div className="space-y-3 pt-3 border-t border-gray-800">
            <p className="text-[11px] text-gray-600">
              <button
                type="button"
                onClick={() => {
                  onClose();
                  if (isGoogle) {
                    onAskChat(`Help me configure the ${connector.name} connector. Use your llmflows-connectors skill. Use gcloud CLI to list my projects, let me pick one, then enable the required APIs and walk me through OAuth setup.`);
                  } else {
                    onAskChat(`Help me configure the ${connector.name} connector. Use your llmflows-connectors skill. Use browser_navigate to open the setup portal and walk me through it — click through the pages for me, I'll handle login when needed.`);
                  }
                }}
                className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 transition"
              >
                <MessageCircle className="w-3 h-3" />
                Ask the agent to configure
              </button>
            </p>
            {isGoogle && (
              <div className="flex items-start gap-2 rounded-lg bg-amber-500/5 border border-amber-500/20 px-3 py-2.5">
                <AlertCircle size={13} className="text-amber-400 mt-0.5 shrink-0" />
                <p className="text-[11px] text-amber-400/80 leading-relaxed">
                  Agent assistant requires <a href="https://cloud.google.com/sdk/docs/install" target="_blank" rel="noopener noreferrer" className="text-amber-300 hover:text-amber-200 underline">gcloud CLI</a> — install it and run <code className="text-[10px] bg-amber-500/10 px-1.5 py-0.5 rounded text-amber-300">gcloud auth login</code> before starting.
                </p>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-2 border-t border-gray-800">
          {isConnected ? (
            <button onClick={doDisconnect} disabled={disconnecting}
              className="text-xs text-gray-500 hover:text-red-400 transition-colors">
              {disconnecting ? "Disconnecting..." : "Disconnect"}
            </button>
          ) : <span />}
          <div className="flex items-center gap-3">
            {saved && <span className="text-xs text-green-400">Saved</span>}
            <button onClick={saveConfig} disabled={saving || (!isConnected && (missingRequired || hasWarnings))}
              className="px-4 py-2 text-xs font-medium rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              {saving ? "Saving..." : isConnected ? "Save" : "Connect"}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

/* ---------- Shared select field ---------- */

function SelectField({
  field, localConfig, setField, inlineFields, showErrors, hasInvalid, saveConfig,
}: {
  field: ConnectorConfigField; localConfig: Record<string, string>;
  setField: (k: string, v: string) => void;
  inlineFields: (sk: string, ov: string) => ConnectorConfigField[];
  showErrors: boolean; hasInvalid: () => boolean; saveConfig: () => void;
}) {
  return (
    <div className="space-y-1.5">
      {field.options?.map((opt) => {
        const isActive = localConfig[field.key] === opt.value;
        const nested = inlineFields(field.key, opt.value);
        return (
          <div key={opt.value}
            className={`flex items-center gap-2.5 rounded-lg border p-3 transition-colors ${
              isActive ? "border-blue-500/50 bg-blue-500/5" : "border-gray-800 bg-gray-900 hover:border-gray-700 cursor-pointer"
            }`}
            onClick={() => !isActive && setField(field.key, opt.value)}>
            <div className={`w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center shrink-0 ${
              isActive ? "border-blue-500" : "border-gray-600"
            }`}>
              {isActive && <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />}
            </div>
            <span className="font-medium text-sm text-white whitespace-nowrap">{opt.label}</span>
            {opt.hint && !isActive && <span className="text-[10px] text-gray-500">{opt.hint}</span>}
            {isActive && nested.length > 0 && nested.map((nf) => {
              const missing = showErrors && !localConfig[nf.key]?.trim();
              return (
                <div key={nf.key} className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                  <input type={nf.type === "secret" ? "password" : "text"}
                    value={localConfig[nf.key] ?? ""}
                    onChange={(e) => setField(nf.key, e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !hasInvalid() && saveConfig()}
                    placeholder={nf.label}
                    className={`bg-gray-800 border rounded px-2 py-1 text-xs w-48 font-mono focus:outline-none ${
                      missing ? "border-amber-500/60" : "border-gray-700 focus:border-gray-500"
                    }`} />
                  {missing && <span className="text-[11px] text-amber-400 whitespace-nowrap">Required</span>}
                </div>
              );
            })}
            {isActive && nested.length === 0 && opt.hint && <span className="text-[10px] text-gray-500">{opt.hint}</span>}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- Connector card ---------- */

function ConnectorBox({ item, onClick, onConnect }: {
  item: UnifiedItem; onClick: () => void; onConnect?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const itemHasWarnings = item.info?.some((i) => i.status === "error") ?? false;

  const handleConnectClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (itemHasWarnings) { onClick(); return; }
    if (!onConnect) return;
    setBusy(true);
    await onConnect();
    setBusy(false);
  };

  const status = item.connected ? "connected"
    : onConnect ? "connect"
    : !item.connected && BUILTIN_IDS.has(item.id) ? "disabled"
    : null;

  return (
    <div onClick={item.connected ? onClick : undefined}
      className={`text-left rounded-xl border border-gray-800 bg-gray-900 hover:border-gray-600 transition-colors p-5 flex items-center gap-4 ${item.connected ? "cursor-pointer" : ""}`}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {status === "connected" && (
            <span className={`w-2 h-2 rounded-full shrink-0 ${itemHasWarnings ? "bg-red-400" : "bg-green-400"}`} />
          )}
          <span className="text-sm font-medium text-white truncate">{item.name}</span>
        </div>
        <span className="text-[11px] text-gray-500 block truncate">{item.description}</span>
      </div>
      <div className="shrink-0 flex items-center gap-2">
        {status === "connect" && (
          <button onClick={handleConnectClick} disabled={busy}
            className="text-[11px] font-medium text-white bg-gray-800 hover:bg-gray-700 border border-gray-700 px-3 py-1 rounded-lg transition-colors disabled:opacity-50">
            {busy ? "Connecting..." : "Connect"}
          </button>
        )}
        {status === "disabled" && (
          <button onClick={(e) => { e.stopPropagation(); onClick(); }}
            className="text-[11px] font-medium text-white bg-gray-800 hover:bg-gray-700 border border-gray-700 px-3 py-1 rounded-lg transition-colors">
            Connect
          </button>
        )}
      </div>
    </div>
  );
}

/* ---------- Main view ---------- */

export function ToolsView() {
  const navigate = useNavigate();
  const [connectors, setConnectors] = useState<ConnectorConfig[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalItem, setModalItem] = useState<UnifiedItem | null>(null);

  const load = async () => {
    try {
      const [c, cat] = await Promise.all([api.getConnectors(), api.getConnectorCatalog()]);
      setConnectors(c); setCatalog(cat);
    } catch (e) { console.error("Failed to load connectors:", e); }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    const onFocus = () => { load(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  const handleUpdate = (updated: ConnectorConfig) => {
    setConnectors((prev) => prev.map((c) => (sid(c) === sid(updated) ? updated : c)));
  };

  const handleInstall = async (item: UnifiedItem) => {
    if (!item.installed && item.catalogEntry) {
      try {
        await api.addConnector({ server_id: item.catalogEntry.server_id });
        await load();
      } catch (e) { console.error("Failed to install:", e); }
    }
  };

  const [connectError, setConnectError] = useState<{ id: string; msg: string } | null>(null);

  const startApiKeyConnect = async (item: UnifiedItem) => {
    if (!item.installed) await handleInstall(item);
    await load();
    const refreshed = (await api.getConnectors()).find((c) => (c.server_id || c.id) === item.id);
    if (refreshed) {
      setConnectors((prev) => {
        const ids = new Set(prev.map((c) => sid(c)));
        return ids.has(sid(refreshed)) ? prev.map((c) => sid(c) === sid(refreshed) ? refreshed : c) : [...prev, refreshed];
      });
      setModalItem({ ...item, installed: true, connector: refreshed });
    }
  };

  const items = buildItems(connectors, catalog);
  const connectedItems = items.filter((i) => i.connected);
  const notConnectedServices = items.filter((i) => !i.connected && !BUILTIN_IDS.has(i.id));
  const builtinTools = items.filter((i) => !i.connected && BUILTIN_IDS.has(i.id));

  const freshModalItem = modalItem ? items.find((i) => i.id === modalItem.id) ?? modalItem : null;

  const isConnectedModal = freshModalItem?.connected && freshModalItem?.connector;
  const isSetupModal = freshModalItem && !freshModalItem.connected && freshModalItem.connector;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="space-y-8">
        <div>
          <h2 className="text-xl font-semibold mb-1">Connectors</h2>
          <p className="text-xs text-gray-500">
            Connect services and configure tools for your flows.
          </p>
        </div>

        {loading && <div className="text-gray-500">Loading...</div>}

        {!loading && (
          <>
            {connectedItems.length > 0 && (
              <section>
                <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-3">Connected</h3>
                <div className="grid grid-cols-3 gap-4">
                  {connectedItems.map((i) => (
                    <ConnectorBox key={i.id} item={i} onClick={() => setModalItem(i)} />
                  ))}
                </div>
              </section>
            )}

            {notConnectedServices.length > 0 && (
              <section>
                <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-3">Not Connected</h3>
                <div className="grid grid-cols-3 gap-4">
                  {notConnectedServices.map((i) => (
                    <ConnectorBox key={i.id} item={i} onClick={() => setModalItem(i)}
                      onConnect={() => startApiKeyConnect(i)} />
                  ))}
                </div>
                {connectError && (
                  <div className="flex items-start gap-2 mt-3 rounded-lg bg-red-500/5 border border-red-500/20 px-4 py-3">
                    <AlertCircle size={14} className="text-red-400 mt-0.5 shrink-0" />
                    <p className="text-xs text-red-400">{connectError.msg}</p>
                    <button onClick={() => setConnectError(null)} className="ml-auto text-red-400/50 hover:text-red-400 shrink-0">
                      <X size={12} />
                    </button>
                  </div>
                )}
              </section>
            )}

            {builtinTools.length > 0 && (
              <section>
                <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-3">Tools</h3>
                <div className="grid grid-cols-3 gap-4">
                  {builtinTools.map((i) => (
                    <ConnectorBox key={i.id} item={i} onClick={() => setModalItem(i)} />
                  ))}
                </div>
              </section>
            )}

          </>
        )}
      </div>

      {freshModalItem && isConnectedModal && (
        <ConfigModal
          connector={freshModalItem.connector!}
          open={!!modalItem}
          onClose={() => setModalItem(null)}
          onUpdate={handleUpdate}
          isConnected
          onAskChat={(prompt) => navigate(`/chat?prompt=${encodeURIComponent(prompt)}&tools=browser`)}
        />
      )}

      {freshModalItem && isSetupModal && (
        <ConfigModal
          connector={freshModalItem.connector!}
          open={!!modalItem}
          onClose={() => setModalItem(null)}
          onUpdate={handleUpdate}
          onAskChat={(prompt) => navigate(`/chat?prompt=${encodeURIComponent(prompt)}&tools=browser`)}
        />
      )}

      {freshModalItem && !freshModalItem.connector && freshModalItem.catalogEntry && (
        <Modal open={!!modalItem} onClose={() => setModalItem(null)}>
          <div className="p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">{freshModalItem.name}</h2>
              <button onClick={() => setModalItem(null)} className="text-gray-500 hover:text-gray-300 p-1"><X size={16} /></button>
            </div>
            <p className="text-sm text-gray-500">{freshModalItem.description}</p>
            {freshModalItem.info && freshModalItem.info.length > 0 && (
              <div className="space-y-1.5">
                {freshModalItem.info.map((item, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${item.status === "ok" ? "bg-green-400" : "bg-red-400"}`} />
                    <span className={`text-xs font-mono ${item.status === "ok" ? "text-gray-500" : "text-red-400/80"}`}>{item.text}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="flex justify-end pt-2 border-t border-gray-800">
              <button onClick={() => setModalItem(null)}
                className="px-4 py-2 text-xs font-medium rounded-lg bg-gray-800 text-white hover:bg-gray-700 transition-colors">
                Close
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
