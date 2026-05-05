import { useState, useEffect, useCallback, useRef } from "react";
import { useParams } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { MarkdownContent } from "@/components/MarkdownContent";
import { Search, Download, Trash2, ExternalLink, Package, ArrowDownWideNarrow } from "lucide-react";
import type { SkillInfo, RegistrySkill } from "@/api/types";

function SkillPreviewModal({
  skill,
  spaceId,
  onClose,
  onRemove,
}: {
  skill: SkillInfo;
  spaceId: string;
  onClose: () => void;
  onRemove?: () => void;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    api.getSkillContent(spaceId, skill.name)
      .then((res) => setContent(res.content))
      .catch(() => setContent("*Failed to load skill content.*"))
      .finally(() => setLoading(false));
  }, [spaceId, skill.name]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleRemove = async () => {
    setRemoving(true);
    try {
      await api.removeSkill(spaceId, skill.name);
      onRemove?.();
      onClose();
    } catch {
      setRemoving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-12 px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70" />
      <div
        className="relative bg-gray-900 border border-gray-700 rounded-xl w-full max-w-3xl max-h-[80vh] flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 shrink-0">
          <div>
            <h3 className="text-base font-mono font-semibold text-gray-100">{skill.name}</h3>
            <div className="flex items-center gap-2 mt-0.5">
              <p className="text-[11px] text-gray-500 font-mono">{skill.path}</p>
              {skill.source && (
                <span className="text-[10px] text-blue-400 bg-blue-400/10 px-1.5 py-0.5 rounded">
                  {skill.source.slug}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRemove}
              disabled={removing}
              className="text-gray-500 hover:text-red-400 transition p-1.5 rounded-lg hover:bg-gray-800"
              title="Remove skill"
            >
              <Trash2 size={14} />
            </button>
            <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg leading-none px-2">
              ✕
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <p className="text-sm text-gray-500 animate-pulse">Loading...</p>
          ) : content ? (
            <MarkdownContent text={content} className="text-sm" />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SkillCard({ skill, onClick }: { skill: SkillInfo; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-left hover:bg-gray-800/50 hover:border-gray-700 transition w-full"
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-mono font-medium text-gray-100">{skill.name}</span>
        {skill.source && (
          <span className="text-[9px] text-blue-400 bg-blue-400/10 px-1.5 py-0.5 rounded shrink-0">
            skills.sh
          </span>
        )}
      </div>
      {skill.description && (
        <p className="text-xs text-gray-400 leading-relaxed mt-1.5">{skill.description}</p>
      )}
      {skill.compatibility && (
        <p className="text-[11px] text-gray-500 mt-1 italic">{skill.compatibility}</p>
      )}
      <p className="text-[11px] text-gray-600 font-mono truncate mt-2">{skill.path}</p>
    </button>
  );
}

function MarketplaceCard({
  skill,
  installed,
  onInstall,
}: {
  skill: RegistrySkill;
  installed: boolean;
  onInstall: (slug: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  const handleInstall = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (installed || busy) return;
    setBusy(true);
    try {
      await onInstall(skill.slug);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Package size={13} className="text-blue-400 shrink-0" />
            <span className="text-sm font-mono font-medium text-gray-100 truncate">{skill.name}</span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-[11px] text-gray-500 font-mono">{skill.owner}/{skill.repo}</p>
            {skill.install_count > 0 && (
              <span className="flex items-center gap-0.5 text-[10px] text-gray-500">
                <ArrowDownWideNarrow size={9} className="text-gray-600" />
                {skill.install_count.toLocaleString()}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <a
            href={skill.github_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-600 hover:text-gray-400 p-1 transition"
            title="View on GitHub"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink size={12} />
          </a>
          {installed ? (
            <span className="text-[10px] text-emerald-400 bg-emerald-400/10 px-2 py-1 rounded-lg font-medium">
              Installed
            </span>
          ) : (
            <button
              onClick={handleInstall}
              disabled={busy}
              className="text-[10px] font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-2.5 py-1 rounded-lg transition flex items-center gap-1"
            >
              <Download size={10} />
              {busy ? "Installing..." : "Install"}
            </button>
          )}
        </div>
      </div>
      {skill.description && (
        <p className="text-xs text-gray-400 leading-relaxed mt-2">{skill.description}</p>
      )}
    </div>
  );
}

function MarketplaceTab({
  spaceId,
  installedNames,
  onInstalled,
}: {
  spaceId: string;
  installedNames: Set<string>;
  onInstalled: () => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RegistrySkill[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); setHasSearched(false); return; }
    setSearching(true);
    setError(null);
    try {
      const res = await api.searchSkills(q);
      setResults(res);
      setHasSearched(true);
    } catch {
      setError("Search failed. GitHub API may be rate-limited.");
    }
    setSearching(false);
  }, []);

  const handleInput = (val: string) => {
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 400);
  };

  const handleInstall = async (slug: string) => {
    try {
      await api.installSkill(spaceId, slug);
      onInstalled();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Install failed");
    }
  };

  return (
    <div>
      <div className="relative mb-4">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
        <input
          type="text"
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          placeholder="Search skills on skills.sh..."
          className="w-full bg-gray-900 border border-gray-700 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50"
        />
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-4">
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}

      {searching && (
        <p className="text-sm text-gray-500 animate-pulse">Searching...</p>
      )}

      {!searching && hasSearched && results.length === 0 && (
        <p className="text-sm text-gray-600">No skills found. Try a different query.</p>
      )}

      {!searching && results.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {results.map((s) => (
            <MarketplaceCard
              key={s.slug}
              skill={s}
              installed={installedNames.has(s.name)}
              onInstall={handleInstall}
            />
          ))}
        </div>
      )}

      {!hasSearched && !searching && (
        <div className="text-center py-8">
          <Package size={32} className="text-gray-700 mx-auto mb-3" />
          <p className="text-sm text-gray-500 mb-1">Search the skills.sh marketplace</p>
          <p className="text-xs text-gray-600">
            Install skills directly from GitHub — type a keyword above to get started.
          </p>
          <p className="text-xs text-gray-600 mt-3 font-mono">
            Or install via CLI: <code className="text-gray-400">llmflows skill add owner/repo@skill</code>
          </p>
        </div>
      )}
    </div>
  );
}

export function SkillsView() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [previewSkill, setPreviewSkill] = useState<SkillInfo | null>(null);
  const [tab, setTab] = useState<"installed" | "marketplace">("installed");

  const load = useCallback(async () => {
    if (!spaceId) return;
    try {
      const sk = await api.listSkills(spaceId);
      setSkills(sk);
    } catch (e) {
      console.error("Skills load error:", e);
    }
  }, [spaceId]);

  useEffect(() => { load(); }, [load]);
  useInterval(load, 10000);

  const installedNames = new Set(skills.map((s) => s.name));

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xl font-semibold">Skills</h2>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Agent skills from <code className="text-gray-400">.agents/skills/</code> and{" "}
        <a href="https://skills.sh" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300">
          skills.sh
        </a>
      </p>

      {/* Tab bar */}
      <div className="flex gap-1 mb-5 border-b border-gray-800">
        <button
          onClick={() => setTab("installed")}
          className={`px-3 py-2 text-sm font-medium transition border-b-2 -mb-px ${
            tab === "installed"
              ? "text-white border-blue-500"
              : "text-gray-500 border-transparent hover:text-gray-300"
          }`}
        >
          Installed ({skills.length})
        </button>
        <button
          onClick={() => setTab("marketplace")}
          className={`px-3 py-2 text-sm font-medium transition border-b-2 -mb-px ${
            tab === "marketplace"
              ? "text-white border-blue-500"
              : "text-gray-500 border-transparent hover:text-gray-300"
          }`}
        >
          Marketplace
        </button>
      </div>

      {tab === "installed" && (
        <>
          {skills.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-sm text-gray-600 mb-2">No skills installed.</p>
              <button
                onClick={() => setTab("marketplace")}
                className="text-sm text-blue-400 hover:text-blue-300 transition"
              >
                Browse the marketplace
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {skills.map((s) => (
                <SkillCard key={s.name} skill={s} onClick={() => setPreviewSkill(s)} />
              ))}
            </div>
          )}
        </>
      )}

      {tab === "marketplace" && spaceId && (
        <MarketplaceTab
          spaceId={spaceId}
          installedNames={installedNames}
          onInstalled={load}
        />
      )}

      {previewSkill && spaceId && (
        <SkillPreviewModal
          skill={previewSkill}
          spaceId={spaceId}
          onClose={() => setPreviewSkill(null)}
          onRemove={load}
        />
      )}
    </div>
  );
}
