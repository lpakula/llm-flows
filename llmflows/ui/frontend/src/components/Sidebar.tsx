import { NavLink } from "react-router-dom";
import { useApp } from "@/App";
import { DaemonWidget } from "./DaemonWidget";

function navClass({ isActive }: { isActive: boolean }) {
  return `w-full text-left px-3 py-1.5 rounded-lg text-sm transition block truncate ${
    isActive ? "bg-gray-800 text-white" : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
  }`;
}

export function Sidebar() {
  const { projects, flows } = useApp();

  return (
    <aside className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col h-full">
      <div className="px-4 py-4 border-b border-gray-800">
        <NavLink to="/" className="text-lg font-semibold tracking-tight hover:text-blue-400 transition">
          llmflows
        </NavLink>
      </div>

      {/* Projects */}
      <div className="px-3 pt-4 pb-2">
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1">Projects</span>
      </div>
      <nav className="px-2 space-y-0.5 flex-shrink-0">
        {projects.map((p) => (
          <NavLink key={p.id} to={`/project/${p.id}`} className={navClass}>
            {p.name}
          </NavLink>
        ))}
        {projects.length === 0 && (
          <div className="px-3 py-2 text-xs text-gray-600 italic">No projects</div>
        )}
      </nav>

      {/* Flows */}
      <div className="px-3 pt-6 pb-2">
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1">Flows</span>
      </div>
      <nav className="px-2 space-y-0.5">
        <NavLink
          to="/flows"
          className={({ isActive }) =>
            navClass({ isActive: isActive || location.hash.startsWith("#/flow-editor") })
          }
        >
          Flows <span className="text-xs text-gray-500 ml-1">({flows.length})</span>
        </NavLink>
      </nav>

      {/* Runs */}
      <div className="px-3 pt-6 pb-2">
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1">Runs</span>
      </div>
      <nav className="px-2 space-y-0.5">
        <NavLink to="/history" className={navClass}>
          History
        </NavLink>
      </nav>

      {/* Integrations */}
      <div className="px-3 pt-6 pb-2">
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1">
          Integrations
        </span>
      </div>
      <nav className="px-2 space-y-0.5">
        <NavLink to="/agents" className={navClass}>
          Agents
        </NavLink>
        <NavLink to="/integrations" className={navClass}>
          GitHub
        </NavLink>
      </nav>

      <div className="flex-1" />

      <DaemonWidget />
    </aside>
  );
}
