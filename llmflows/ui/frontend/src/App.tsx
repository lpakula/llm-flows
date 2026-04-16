import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useState, useEffect, useCallback, useMemo, createContext, useContext } from "react";
import { api } from "@/api/client";
import type { Space } from "@/api/types";
import { Layout } from "@/components/Layout";
import { Dashboard } from "@/views/Dashboard";
import { InboxView } from "@/views/Inbox";
import { SpaceView } from "@/views/Space";
import { RunDetailView } from "@/views/RunDetail";
import { SpaceFlowsView } from "@/views/Flows";
import { FlowEditorView } from "@/views/FlowEditor";
import { AgentsView } from "@/views/Agents";
import { GatewayView } from "@/views/Gateway";
import { SettingsView } from "@/views/Settings";
import { SpaceSettingsView } from "@/views/SpaceSettings";
import { SkillsView } from "@/views/Skills";

interface AppContextType {
  spaces: Space[];
  selectedSpaceId: string | null;
  setSelectedSpaceId: (id: string | null) => void;
  reload: () => Promise<void>;
}

const AppContext = createContext<AppContextType>({
  spaces: [],
  selectedSpaceId: null,
  setSelectedSpaceId: () => {},
  reload: async () => {},
});

export function useApp() {
  return useContext(AppContext);
}

function AppInner() {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [manualSpaceId, setManualSpaceId] = useState<string | null>(null);
  const location = useLocation();

  const reload = useCallback(async () => {
    const s = await api.listSpaces();
    setSpaces(s);
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const urlSpaceId = useMemo(() => {
    const m = location.pathname.match(/\/space\/([a-z0-9]+)/);
    return m ? m[1] : null;
  }, [location.pathname]);

  useEffect(() => {
    if (urlSpaceId) setManualSpaceId(urlSpaceId);
  }, [urlSpaceId]);

  const selectedSpaceId = urlSpaceId || manualSpaceId;

  return (
    <AppContext.Provider value={{ spaces, selectedSpaceId, setSelectedSpaceId: setManualSpaceId, reload }}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/inbox" element={<InboxView />} />
          <Route path="/space/:spaceId" element={<SpaceView />} />
          <Route path="/space/:spaceId/flows" element={<SpaceFlowsView />} />
          <Route path="/space/:spaceId/run/:runId" element={<RunDetailView />} />
          <Route path="/space/:spaceId/skills" element={<SkillsView />} />
          <Route path="/space/:spaceId/settings" element={<SpaceSettingsView />} />
          <Route path="/flow-editor/:flowId" element={<FlowEditorView />} />
          <Route path="/agents" element={<AgentsView />} />
          <Route path="/gateway" element={<GatewayView />} />
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
