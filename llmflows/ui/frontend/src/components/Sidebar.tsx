import { useState, useEffect, useRef, useCallback } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { LayoutDashboard, Workflow, Settings, Bot, SlidersHorizontal, Inbox, Radio, BookOpen } from "lucide-react";
import { useApp } from "@/App";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { DaemonWidget } from "./DaemonWidget";

function navClass({ isActive }: { isActive: boolean }) {
  return `w-full text-left px-3 py-1.5 rounded-lg text-sm transition flex items-center gap-2.5 ${
    isActive ? "bg-gray-800 text-white" : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
  }`;
}

export function Sidebar() {
  const { projects, selectedProjectId, setSelectedProjectId } = useApp();
  const navigate = useNavigate();
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const projectPickerRef = useRef<HTMLDivElement>(null);
  const [inboxCount, setInboxCount] = useState(0);

  const selectedProject = projects.find((p) => p.id === selectedProjectId) || null;

  const refreshInbox = useCallback(async () => {
    try {
      const data = await api.getInbox();
      setInboxCount(data.count);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { refreshInbox(); }, [refreshInbox]);
  useInterval(refreshInbox, 10000);

  useEffect(() => {
    const onDocMouseDown = (e: MouseEvent) => {
      if (projectPickerRef.current && !projectPickerRef.current.contains(e.target as Node)) {
        setProjectMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  const pickProject = (id: string | null) => {
    setProjectMenuOpen(false);
    if (id) {
      setSelectedProjectId(id);
      navigate(`/project/${id}`);
    } else {
      setSelectedProjectId(null);
      navigate("/");
    }
  };

  return (
    <aside className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col h-full min-h-0">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-800 flex-shrink-0 flex items-center justify-center">
        <NavLink to="/" className="text-lg font-semibold tracking-tight hover:text-blue-400 transition">
          llm flows
        </NavLink>
      </div>

      {/* Inbox — project-agnostic, always visible */}
      <nav className="flex-shrink-0 border-b border-gray-800 px-2 py-2">
        <NavLink to="/inbox" className={navClass}>
          <Inbox size={14} className="flex-shrink-0" />
          <span className="flex-1">Inbox</span>
          {inboxCount > 0 && (
            <span className="ml-auto bg-amber-500/20 text-amber-400 text-[10px] font-semibold px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
              {inboxCount}
            </span>
          )}
        </NavLink>
      </nav>

      {/* Project picker (inline expand) + project nav */}
      <div className="flex-shrink-0 border-b border-gray-800 px-3 pt-3 pb-2" ref={projectPickerRef}>
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1 block mb-1.5">
          Project
        </span>
        <div className="rounded-lg border border-gray-700 bg-gray-800/80 overflow-hidden">
          <button
            type="button"
            onClick={() => setProjectMenuOpen((o) => !o)}
            aria-expanded={projectMenuOpen}
            aria-haspopup="listbox"
            className="w-full text-left px-2.5 py-2 text-sm text-gray-200 flex items-center gap-2 hover:bg-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset"
          >
            <span className="text-gray-400 shrink-0 w-3 text-center" aria-hidden>
              {selectedProject ? "✓" : ""}
            </span>
            <span className="truncate">{selectedProject?.name ?? "Select project..."}</span>
          </button>
          {projectMenuOpen && (
            <ul
              role="listbox"
              className="border-t border-gray-700 max-h-52 overflow-y-auto divide-y divide-gray-800/80"
            >
              <li role="option" aria-selected={!selectedProjectId}>
                <button
                  type="button"
                  onClick={() => pickProject(null)}
                  className={`w-full text-left px-2.5 py-2 text-sm flex items-center gap-2 transition-colors duration-100 ${
                    !selectedProjectId
                      ? "bg-blue-600/25 text-white hover:bg-blue-500/40"
                      : "text-gray-300 hover:bg-gray-700"
                  }`}
                >
                  <span className="w-3 shrink-0 text-center text-xs">{!selectedProjectId ? "✓" : ""}</span>
                  <span className="truncate">Select project...</span>
                </button>
              </li>
              {projects.map((p) => (
                <li key={p.id} role="option" aria-selected={p.id === selectedProjectId}>
                  <button
                    type="button"
                    onClick={() => pickProject(p.id)}
                    className={`w-full text-left px-2.5 py-2 text-sm flex items-center gap-2 transition-colors duration-100 ${
                      p.id === selectedProjectId
                        ? "bg-blue-600/25 text-white hover:bg-blue-500/40"
                        : "text-gray-300 hover:bg-gray-700"
                    }`}
                  >
                    <span className="w-3 shrink-0 text-center text-xs">{p.id === selectedProjectId ? "✓" : ""}</span>
                    <span className="truncate">{p.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <nav className="flex-1 min-h-0 overflow-y-auto px-2 pt-2 space-y-0.5">
        {selectedProject && (
          <>
            <NavLink to={`/project/${selectedProject.id}`} end className={navClass}>
              <LayoutDashboard size={14} className="flex-shrink-0" />
              Board
            </NavLink>
            <NavLink to={`/project/${selectedProject.id}/flows`} className={navClass}>
              <Workflow size={14} className="flex-shrink-0" />
              Flows
            </NavLink>
            <NavLink to={`/project/${selectedProject.id}/skills`} className={navClass}>
              <BookOpen size={14} className="flex-shrink-0" />
              Skills
            </NavLink>
            <NavLink to={`/project/${selectedProject.id}/settings`} className={navClass}>
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
