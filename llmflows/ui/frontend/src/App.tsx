import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useState, useEffect, useCallback, useMemo, createContext, useContext } from "react";
import { api } from "@/api/client";
import type { Project } from "@/api/types";
import { Layout } from "@/components/Layout";
import { Dashboard } from "@/views/Dashboard";
import { ProjectView } from "@/views/Project";
import { TaskView } from "@/views/Task";
import { ProjectFlowsView } from "@/views/Flows";
import { FlowEditorView } from "@/views/FlowEditor";
import { AgentsView } from "@/views/Agents";
import { SettingsView } from "@/views/Settings";
import { ProjectSettingsView } from "@/views/ProjectSettings";

interface AppContextType {
  projects: Project[];
  selectedProjectId: string | null;
  setSelectedProjectId: (id: string | null) => void;
  reload: () => Promise<void>;
}

const AppContext = createContext<AppContextType>({
  projects: [],
  selectedProjectId: null,
  setSelectedProjectId: () => {},
  reload: async () => {},
});

export function useApp() {
  return useContext(AppContext);
}

function AppInner() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [manualProjectId, setManualProjectId] = useState<string | null>(null);
  const location = useLocation();

  const reload = useCallback(async () => {
    const p = await api.listProjects();
    setProjects(p);
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const urlProjectId = useMemo(() => {
    const m = location.pathname.match(/\/project\/([a-z0-9]+)/);
    return m ? m[1] : null;
  }, [location.pathname]);

  useEffect(() => {
    if (urlProjectId) setManualProjectId(urlProjectId);
  }, [urlProjectId]);

  const selectedProjectId = urlProjectId || manualProjectId;

  return (
    <AppContext.Provider value={{ projects, selectedProjectId, setSelectedProjectId: setManualProjectId, reload }}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/project/:projectId" element={<ProjectView />} />
          <Route path="/project/:projectId/flows" element={<ProjectFlowsView />} />
          <Route path="/project/:projectId/task/:taskId" element={<TaskView />} />
          <Route path="/project/:projectId/settings" element={<ProjectSettingsView />} />
          <Route path="/flow-editor/:flowId" element={<FlowEditorView />} />
          <Route path="/agents" element={<AgentsView />} />
          <Route path="/settings" element={<SettingsView />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AppContext.Provider>
  );
}

export function App() {
  return <AppInner />;
}
