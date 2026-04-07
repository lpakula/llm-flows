import { Routes, Route, Navigate } from "react-router-dom";
import { useState, useEffect, useCallback, createContext, useContext } from "react";
import { api } from "@/api/client";
import type { Project, Flow } from "@/api/types";
import { Layout } from "@/components/Layout";
import { Dashboard } from "@/views/Dashboard";
import { ProjectView } from "@/views/Project";
import { TaskView } from "@/views/Task";
import { FlowsView } from "@/views/Flows";
import { FlowEditorView } from "@/views/FlowEditor";
import { HistoryView } from "@/views/History";
import { AgentsView } from "@/views/Agents";
import { IntegrationsView } from "@/views/Integrations";
import { SettingsView } from "@/views/Settings";

interface AppContextType {
  projects: Project[];
  flows: Flow[];
  reload: () => Promise<void>;
}

const AppContext = createContext<AppContextType>({
  projects: [],
  flows: [],
  reload: async () => {},
});

export function useApp() {
  return useContext(AppContext);
}

export function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [flows, setFlows] = useState<Flow[]>([]);

  const reload = useCallback(async () => {
    const [p, f] = await Promise.all([api.listProjects(), api.listFlows()]);
    setProjects(p);
    setFlows(f);
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <AppContext.Provider value={{ projects, flows, reload }}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/project/:projectId" element={<ProjectView />} />
          <Route path="/task/:taskId" element={<TaskView />} />
          <Route path="/flows" element={<FlowsView />} />
          <Route path="/flow-editor/:flowId" element={<FlowEditorView />} />
          <Route path="/history" element={<HistoryView />} />
          <Route path="/agents" element={<AgentsView />} />
          <Route path="/integrations" element={<IntegrationsView />} />
          <Route path="/settings" element={<SettingsView />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AppContext.Provider>
  );
}
