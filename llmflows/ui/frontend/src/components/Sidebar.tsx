import { useState, useEffect, useRef, useCallback } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { Workflow, Settings, Bot, SlidersHorizontal, Inbox, Radio, BookOpen, Wrench, MessageCircle, FolderPlus, Folder, FolderGit2, ChevronUp, Loader2 } from "lucide-react";
import { useApp } from "@/App";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { DaemonWidget } from "./DaemonWidget";

function navClass({ isActive }: { isActive: boolean }) {
  return `w-full text-left px-3 py-1.5 rounded-lg text-sm transition flex items-center gap-2.5 ${
    isActive ? "bg-gray-800 text-white" : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
  }`;
}

interface DirEntry {
  name: string;
  path: string;
  has_git: boolean;
  has_flows: boolean;
}

function RegisterSpaceModal({ onClose, onRegistered }: { onClose: () => void; onRegistered: (id: string) => void }) {
  const [currentPath, setCurrentPath] = useState("~");
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [dirs, setDirs] = useState<DirEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [spaceName, setSpaceName] = useState("");
  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  const browse = useCallback(async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.browseDirs(path);
      setCurrentPath(data.current);
      setParentPath(data.parent);
      setDirs(data.dirs);
    } catch {
      setError("Cannot access this directory");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { browse("~"); }, [browse]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleSelect = (dir: DirEntry) => {
    setSelectedPath(dir.path);
    setSpaceName(dir.name);
  };

  const handleRegister = async () => {
    const pathToRegister = selectedPath || currentPath;
    if (!pathToRegister) return;
    setRegistering(true);
    setError(null);
    try {
      const space = await api.registerSpace(pathToRegister, spaceName || undefined);
      onRegistered(space.id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setRegistering(false);
    }
  };

  const resolvedName = spaceName || (selectedPath ? selectedPath.split("/").pop() : currentPath.split("/").pop()) || "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={modalRef} className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-[480px] max-h-[80vh] flex flex-col">
        <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-base font-semibold text-white">Register Space</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg leading-none">&times;</button>
        </div>

        <div className="px-5 py-3 border-b border-gray-800 flex items-center gap-2 text-xs text-gray-400 bg-gray-800/40">
          {parentPath && (
            <button onClick={() => browse(parentPath)} className="p-1 hover:bg-gray-700 rounded transition" title="Go up">
              <ChevronUp size={14} />
            </button>
          )}
          <span className="truncate font-mono">{currentPath}</span>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-8 text-gray-500">
              <Loader2 size={18} className="animate-spin" />
            </div>
          ) : dirs.length === 0 ? (
            <div className="py-8 text-center text-gray-500 text-sm">No subdirectories</div>
          ) : (
            <ul className="divide-y divide-gray-800/60">
              {dirs.map((d) => (
                <li key={d.path}>
                  <div className="flex items-center">
                    <button
                      onClick={() => handleSelect(d)}
                      className={`flex-1 text-left px-4 py-2 text-sm flex items-center gap-2.5 transition-colors ${
                        selectedPath === d.path ? "bg-blue-600/20 text-white" : "text-gray-300 hover:bg-gray-800"
                      }`}
                    >
                      {d.has_git ? <FolderGit2 size={14} className="text-orange-400 shrink-0" /> : <Folder size={14} className="text-gray-500 shrink-0" />}
                      <span className="truncate">{d.name}</span>
                      {d.has_flows && <span className="ml-auto text-[10px] text-emerald-400 bg-emerald-400/10 px-1.5 py-0.5 rounded">flows</span>}
                    </button>
                    <button
                      onClick={() => browse(d.path)}
                      className="px-3 py-2 text-gray-500 hover:text-gray-200 hover:bg-gray-800 text-xs transition"
                      title="Browse into"
                    >
                      &rsaquo;
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="px-5 py-4 border-t border-gray-800 space-y-3">
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500 shrink-0 w-12">Name</label>
            <input
              type="text"
              value={spaceName}
              onChange={(e) => setSpaceName(e.target.value)}
              placeholder={resolvedName}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500 shrink-0 w-12">Path</label>
            <span className="flex-1 text-xs text-gray-400 font-mono truncate">{selectedPath || currentPath}</span>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-400 hover:text-white transition">Cancel</button>
            <button
              onClick={handleRegister}
              disabled={registering}
              className="px-4 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg transition flex items-center gap-2"
            >
              {registering && <Loader2 size={14} className="animate-spin" />}
              Register
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Sidebar() {
  const { spaces, selectedSpaceId, setSelectedSpaceId, reload } = useApp();
  const navigate = useNavigate();
  const [spaceMenuOpen, setSpaceMenuOpen] = useState(false);
  const [showRegister, setShowRegister] = useState(false);
  const spacePickerRef = useRef<HTMLDivElement>(null);
  const [inboxCount, setInboxCount] = useState(0);

  const selectedSpace = spaces.find((s) => s.id === selectedSpaceId) || null;

  const refreshInbox = useCallback(async () => {
    try {
      const data = await api.getInbox();
      setInboxCount(data.count);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { refreshInbox(); }, [refreshInbox]);
  useInterval(refreshInbox, 10000);

  useEffect(() => {
    const onInboxChanged = () => { refreshInbox(); };
    window.addEventListener("inbox-updated", onInboxChanged);
    return () => window.removeEventListener("inbox-updated", onInboxChanged);
  }, [refreshInbox]);

  useEffect(() => {
    const onDocMouseDown = (e: MouseEvent) => {
      if (spacePickerRef.current && !spacePickerRef.current.contains(e.target as Node)) {
        setSpaceMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  const pickSpace = (id: string | null) => {
    setSpaceMenuOpen(false);
    if (id) {
      setSelectedSpaceId(id);
      navigate(`/space/${id}/flows`);
    } else {
      setSelectedSpaceId(null);
      navigate("/");
    }
  };

  const handleRegistered = async (spaceId: string) => {
    setShowRegister(false);
    await reload();
    pickSpace(spaceId);
  };

  return (
    <aside className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col h-full min-h-0">
      {showRegister && <RegisterSpaceModal onClose={() => setShowRegister(false)} onRegistered={handleRegistered} />}

      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-800 flex-shrink-0 flex items-center justify-center">
        <NavLink to="/" className="text-lg font-semibold tracking-tight hover:text-blue-400 transition">
          llm flows
        </NavLink>
      </div>

      {/* Inbox + Chat — space-agnostic, always visible */}
      <nav className="flex-shrink-0 border-b border-gray-800 px-2 py-2 space-y-0.5">
        <NavLink to="/inbox" className={navClass}>
          <Inbox size={14} className="flex-shrink-0" />
          <span className="flex-1">Inbox</span>
          {inboxCount > 0 && (
            <span className="ml-auto bg-amber-500/20 text-amber-400 text-[10px] font-semibold px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
              {inboxCount}
            </span>
          )}
        </NavLink>
        <NavLink to="/chat" className={navClass}>
          <MessageCircle size={14} className="flex-shrink-0" />
          Chat
        </NavLink>
      </nav>

      {/* Space picker (inline expand) + space nav */}
      <div className="flex-shrink-0 border-b border-gray-800 px-3 pt-3 pb-2" ref={spacePickerRef}>
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1 block mb-1.5">
          Space
        </span>
        <div className="rounded-lg border border-gray-700 bg-gray-800/80 overflow-hidden">
          <button
            type="button"
            onClick={() => setSpaceMenuOpen((o) => !o)}
            aria-expanded={spaceMenuOpen}
            aria-haspopup="listbox"
            className="w-full text-left px-2.5 py-2 text-sm text-gray-200 flex items-center gap-2 hover:bg-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset"
          >
            <span className="text-gray-400 shrink-0 w-3 text-center" aria-hidden>
              {selectedSpace ? "✓" : ""}
            </span>
            <span className="truncate">{selectedSpace?.name ?? "Select space..."}</span>
          </button>
          {spaceMenuOpen && (
            <ul
              role="listbox"
              className="border-t border-gray-700 max-h-52 overflow-y-auto divide-y divide-gray-800/80"
            >
              <li role="option" aria-selected={!selectedSpaceId}>
                <button
                  type="button"
                  onClick={() => pickSpace(null)}
                  className={`w-full text-left px-2.5 py-2 text-sm flex items-center gap-2 transition-colors duration-100 ${
                    !selectedSpaceId
                      ? "bg-blue-600/25 text-white hover:bg-blue-500/40"
                      : "text-gray-300 hover:bg-gray-700"
                  }`}
                >
                  <span className="w-3 shrink-0 text-center text-xs">{!selectedSpaceId ? "✓" : ""}</span>
                  <span className="truncate">Select space...</span>
                </button>
              </li>
              {spaces.map((s) => (
                <li key={s.id} role="option" aria-selected={s.id === selectedSpaceId}>
                  <button
                    type="button"
                    onClick={() => pickSpace(s.id)}
                    className={`w-full text-left px-2.5 py-2 text-sm flex items-center gap-2 transition-colors duration-100 ${
                      s.id === selectedSpaceId
                        ? "bg-blue-600/25 text-white hover:bg-blue-500/40"
                        : "text-gray-300 hover:bg-gray-700"
                    }`}
                  >
                    <span className="w-3 shrink-0 text-center text-xs">{s.id === selectedSpaceId ? "✓" : ""}</span>
                    <span className="truncate">{s.name}</span>
                  </button>
                </li>
              ))}
              <li>
                <button
                  type="button"
                  onClick={() => { setSpaceMenuOpen(false); setShowRegister(true); }}
                  className="w-full text-left px-2.5 py-2 text-sm flex items-center gap-2 text-blue-400 hover:bg-gray-700 transition-colors duration-100"
                >
                  <FolderPlus size={12} className="shrink-0" />
                  <span>Register space...</span>
                </button>
              </li>
            </ul>
          )}
        </div>
      </div>

      <nav className="flex-1 min-h-0 overflow-y-auto px-2 pt-2 space-y-0.5">
        {selectedSpace && (
          <>
            <NavLink to={`/space/${selectedSpace.id}/flows`} className={navClass}>
              <Workflow size={14} className="flex-shrink-0" />
              Flows
            </NavLink>
            <NavLink to={`/space/${selectedSpace.id}/skills`} className={navClass}>
              <BookOpen size={14} className="flex-shrink-0" />
              Skills
            </NavLink>
            <NavLink to={`/space/${selectedSpace.id}/settings`} className={navClass}>
              <Settings size={14} className="flex-shrink-0" />
              Settings
            </NavLink>
          </>
        )}
      </nav>

      <div className="flex-shrink-0 border-t border-gray-800 pt-2 pb-1">
        <div className="px-3 pb-1">
          <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1">Config</span>
        </div>
        <nav className="px-2 space-y-0.5 pb-2">
          <NavLink to="/agents" className={navClass}>
            <Bot size={14} className="flex-shrink-0" />
            Agents
          </NavLink>
          <NavLink to="/tools" className={navClass}>
            <Wrench size={14} className="flex-shrink-0" />
            Tools
          </NavLink>
          <NavLink to="/gateway" className={navClass}>
            <Radio size={14} className="flex-shrink-0" />
            Gateway
          </NavLink>
          <NavLink to="/settings" className={navClass}>
            <SlidersHorizontal size={14} className="flex-shrink-0" />
            Settings
          </NavLink>
        </nav>

        <DaemonWidget />
      </div>
    </aside>
  );
}
