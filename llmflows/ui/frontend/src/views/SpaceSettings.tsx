import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useApp } from "@/App";
import { useInterval } from "@/hooks/useInterval";
import { ShieldCheck, ShieldAlert, ShieldOff } from "lucide-react";
import { SecurityAuditModal, type AuditResource } from "@/components/SecurityAuditModal";
import type { Space, SpaceSettings, Flow, SkillInfo } from "@/api/types";

export function SpaceSettingsView() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const navigate = useNavigate();
  const { reload: reloadApp } = useApp();

  const [space, setSpace] = useState<Space | null>(null);
  const [settings, setSettings] = useState<SpaceSettings | null>(null);
  const [loading, setLoading] = useState(true);

  const [nameValue, setNameValue] = useState("");
  const [nameDirty, setNameDirty] = useState(false);
  const [nameSaving, setNameSaving] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);

  const [flows, setFlows] = useState<Flow[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [showAuditModal, setShowAuditModal] = useState(false);

  const refreshAudit = useCallback(async () => {
    if (!spaceId) return;
    try {
      const [f, s] = await Promise.all([api.listFlows(spaceId), api.listSkills(spaceId)]);
      setFlows(f);
      setSkills(s);
    } catch { /* ignore */ }
  }, [spaceId]);
  useEffect(() => { refreshAudit(); }, [refreshAudit]);
  useInterval(refreshAudit, 10000);

  const unsafeFlows = flows.filter((f) => f.audit?.status === "unsafe").length;
  const unauditedFlows = flows.filter((f) => !f.audit?.status).length;
  const unsafeSkills = skills.filter((s) => s.audit?.status === "unsafe").length;
  const unauditedSkills = skills.filter((s) => !s.audit?.status).length;
  const totalUnsafe = unsafeFlows + unsafeSkills;
  const totalUnaudited = unauditedFlows + unauditedSkills;
  const allClear = totalUnsafe === 0 && totalUnaudited === 0;

  useEffect(() => {
    if (!spaceId) return;
    (async () => {
      try {
        const [s, st] = await Promise.all([
          api.getSpace(spaceId),
          api.getSpaceSettings(spaceId),
        ]);
        setSpace(s);
        setSettings(st);
        setNameValue(s.name);
      } catch (e) {
        console.error("Failed to load space settings:", e);
      }
      setLoading(false);
    })();
  }, [spaceId]);

  const saveName = async () => {
    if (!space || !nameValue.trim()) return;
    setNameSaving(true);
    try {
      const updated = await api.updateSpace(space.id, { name: nameValue.trim() });
      setSpace(updated);
      setNameDirty(false);
      setNameSaved(true);
      setTimeout(() => setNameSaved(false), 2000);
      reloadApp();
    } catch (e) {
      console.error("Failed to rename space:", e);
    }
    setNameSaving(false);
  };

  const deleteSpace = async () => {
    if (!space || !confirm(`Delete space "${space.name}"? All runs and flows will be lost.`)) return;
    await api.deleteSpace(space.id);
    reloadApp();
    navigate("/");
  };

  if (loading) {
    return <div className="flex-1 overflow-y-auto p-6 text-gray-500">Loading...</div>;
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mb-6">
        <button
          onClick={() => navigate(`/space/${spaceId}/flows`)}
          className="text-xs text-gray-500 hover:text-gray-300 mb-3 block"
        >
          &larr; Back to flows
        </button>
        <h2 className="text-xl font-semibold">Space Settings</h2>
        {space && (
          <p className="text-xs text-gray-500 mt-1 font-mono">{space.path}</p>
        )}
      </div>

      <div className="border border-gray-800 rounded-xl overflow-hidden mb-8">
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
              <td className="px-4 py-3 font-medium text-white whitespace-nowrap">Name</td>
              <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">Display name for this space</td>
              <td className="px-4 py-3">
                <input
                  value={nameValue}
                  onChange={(e) => { setNameValue(e.target.value); setNameDirty(true); }}
                  onKeyDown={(e) => e.key === "Enter" && saveName()}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-64 focus:outline-none focus:border-gray-500"
                />
              </td>
              <td className="px-4 py-3 text-right">
                {nameSaved ? (
                  <span className="text-xs text-green-400">Saved</span>
                ) : (
                  <button
                    onClick={saveName}
                    disabled={!nameDirty || nameSaving || !nameValue.trim()}
                    className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                  >
                    {nameSaving ? "Saving..." : "Save"}
                  </button>
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="border border-gray-800 rounded-xl overflow-hidden mb-8">
        <div className="px-4 py-3 bg-gray-900/60 border-b border-gray-800">
          <h3 className="text-sm font-medium text-white">Security</h3>
        </div>
        <div className="px-4 py-4 bg-gray-900 border-b border-gray-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {allClear ? (
                <ShieldCheck size={18} className="text-emerald-400" />
              ) : totalUnsafe > 0 ? (
                <ShieldAlert size={18} className="text-red-400" />
              ) : (
                <ShieldOff size={18} className="text-amber-400" />
              )}
              <div>
                {allClear ? (
                  <p className="text-sm text-emerald-400 font-medium">All resources passed security audit</p>
                ) : (
                  <p className="text-sm text-white">
                    {totalUnsafe > 0 && <span className="text-red-400 font-medium">{totalUnsafe} unsafe</span>}
                    {totalUnsafe > 0 && totalUnaudited > 0 && <span className="text-gray-500 mx-1.5">·</span>}
                    {totalUnaudited > 0 && <span className="text-amber-400 font-medium">{totalUnaudited} unaudited</span>}
                  </p>
                )}
                <p className="text-xs text-gray-500 mt-0.5">
                  {flows.length} flow{flows.length !== 1 ? "s" : ""}, {skills.length} skill{skills.length !== 1 ? "s" : ""}
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowAuditModal(true)}
              className="text-xs text-blue-400 hover:text-blue-300 transition font-medium"
            >
              View details
            </button>
          </div>
        </div>
        <div className="px-4 py-3 bg-gray-900 border-b border-gray-800 flex items-center justify-between">
          <div>
            <p className="text-sm text-white">Security audit on import</p>
            <p className="text-xs text-gray-500 mt-0.5">Automatically run security audit before flows are imported</p>
          </div>
          <button
            onClick={async () => {
              if (!spaceId || !settings) return;
              const updated = await api.updateSpaceSettings(spaceId, {
                audit_flows_on_import: !settings.audit_flows_on_import,
              });
              setSettings(updated);
            }}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ${
              settings?.audit_flows_on_import ? "bg-blue-600" : "bg-gray-700"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                settings?.audit_flows_on_import ? "translate-x-[18px]" : "translate-x-[3px]"
              }`}
            />
          </button>
        </div>
        <div className="px-4 py-3 bg-gray-900 flex items-center justify-between">
          <div>
            <p className="text-sm text-white">Block unsafe runs</p>
            <p className="text-xs text-gray-500 mt-0.5">Require security audit to pass before runs can be enqueued</p>
          </div>
          <button
            onClick={async () => {
              if (!spaceId || !settings) return;
              const updated = await api.updateSpaceSettings(spaceId, {
                block_unsafe_runs: !settings.block_unsafe_runs,
              });
              setSettings(updated);
            }}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ${
              settings?.block_unsafe_runs ? "bg-blue-600" : "bg-gray-700"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                settings?.block_unsafe_runs ? "translate-x-[18px]" : "translate-x-[3px]"
              }`}
            />
          </button>
        </div>
      </div>

      {spaceId && (
        <SecurityAuditModal
          open={showAuditModal}
          onClose={() => setShowAuditModal(false)}
          flows={flows.map((f): AuditResource => ({
            name: f.name,
            key: f.id,
            link: `/space/${spaceId}/flow/${f.id}`,
            audit: f.audit ?? null,
          }))}
          skills={skills.map((s): AuditResource => ({
            name: s.name,
            key: s.name,
            audit: s.audit ?? null,
          }))}
          onAuditFlow={(flowId) => api.runFlowAudit(flowId)}
          onAuditSkill={(skillName) => api.runSkillAudit(spaceId, skillName)}
          onComplete={refreshAudit}
        />
      )}

      <div className="border border-red-900/50 rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-red-950/20 border-b border-red-900/50">
          <h3 className="text-sm font-medium text-red-400">Danger zone</h3>
        </div>
        <div className="px-4 py-4 bg-gray-900 flex items-center justify-between">
          <div>
            <p className="text-sm text-white">Delete this space</p>
            <p className="text-xs text-gray-500 mt-0.5">All flow runs and flows associated with this space will be permanently deleted.</p>
          </div>
          <button
            onClick={deleteSpace}
            className="ml-6 px-4 py-1.5 text-xs bg-red-700 hover:bg-red-600 text-white rounded-lg transition-colors shrink-0"
          >
            Delete space
          </button>
        </div>
      </div>
    </div>
  );
}
