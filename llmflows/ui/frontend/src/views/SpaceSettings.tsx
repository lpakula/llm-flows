import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useApp } from "@/App";
import type { Space } from "@/api/types";

export function SpaceSettingsView() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const navigate = useNavigate();
  const { reload: reloadApp } = useApp();

  const [space, setSpace] = useState<Space | null>(null);
  const [loading, setLoading] = useState(true);

  const [nameValue, setNameValue] = useState("");
  const [nameDirty, setNameDirty] = useState(false);
  const [nameSaving, setNameSaving] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);

  useEffect(() => {
    if (!spaceId) return;
    (async () => {
      try {
        const s = await api.getSpace(spaceId);
        setSpace(s);
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
