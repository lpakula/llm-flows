import { NavLink, useNavigate } from "react-router-dom";
import { useApp } from "@/App";
import { DaemonWidget } from "./DaemonWidget";

function navClass({ isActive }: { isActive: boolean }) {
  return `w-full text-left px-3 py-1.5 rounded-lg text-sm transition block truncate ${
    isActive ? "bg-gray-800 text-white" : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
  }`;
}

export function Sidebar() {
  const { projects, selectedProjectId, setSelectedProjectId } = useApp();
  const navigate = useNavigate();

  const selectedProject = projects.find((p) => p.id === selectedProjectId) || null;

  const handleProjectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    if (id) {
      setSelectedProjectId(id);
      navigate(`/project/${id}`);
    } else {
      setSelectedProjectId(null);
      navigate("/");
    }
  };

  return (
    <aside className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col h-full">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-800">
        <NavLink to="/" className="text-lg font-semibold tracking-tight hover:text-blue-400 transition">
          llmflows
        </NavLink>
      </div>

      {/* Project selector */}
      <div className="px-3 pt-4 pb-1">
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1">Project</span>
      </div>
      <div className="px-3 pb-2">
        <select
          value={selectedProjectId || ""}
          onChange={handleProjectChange}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 truncate appearance-none cursor-pointer"
        >
          <option value="">Select project...</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      {/* Project context nav */}
      {selectedProject && (
        <nav className="px-2 space-y-0.5 border-t border-gray-800 pt-2">
          <NavLink to={`/project/${selectedProject.id}`} end className={navClass}>
            Tasks
          </NavLink>
          <NavLink to={`/project/${selectedProject.id}/flows`} className={navClass}>
            Flows
          </NavLink>
        </nav>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Global config -- sticky bottom */}
      <div className="border-t border-gray-800 pt-2 pb-1">
        <div className="px-3 pb-1">
          <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium px-1">Config</span>
        </div>
        <nav className="px-2 space-y-0.5">
          <NavLink to="/agents" className={navClass}>
            Agents
          </NavLink>
          <NavLink to="/settings" className={navClass}>
            Settings
          </NavLink>
        </nav>
      </div>

      <DaemonWidget />
    </aside>
  );
}
