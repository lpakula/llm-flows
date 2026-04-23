import { Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useState, useEffect, useCallback, useMemo, createContext, useContext } from "react";
import { api } from "@/api/client";
import type { Space } from "@/api/types";
import { Layout } from "@/components/Layout";
import { InboxView } from "@/views/Inbox";
import { SpaceFlowsView } from "@/views/Flows";
import { FlowDetailView } from "@/views/FlowDetail";
import { AgentsView } from "@/views/Agents";
import { GatewayView } from "@/views/Gateway";
import { ToolsView } from "@/views/Tools";
import { SettingsView } from "@/views/Settings";
import { SpaceSettingsView } from "@/views/SpaceSettings";
import { SkillsView } from "@/views/Skills";
import { ChatView } from "@/views/Chat";
import { WelcomeView } from "@/views/Welcome";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatState {
  messages: ChatMessage[];
  sessionId: string | null;
}

interface AppContextType {
  spaces: Space[];
  selectedSpaceId: string | null;
  setSelectedSpaceId: (id: string | null) => void;
  reload: () => Promise<void>;
  chatState: ChatState;
  setChatState: React.Dispatch<React.SetStateAction<ChatState>>;
}

const AppContext = createContext<AppContextType>({
  spaces: [],
  selectedSpaceId: null,
  setSelectedSpaceId: () => {},
  reload: async () => {},
  chatState: { messages: [], sessionId: null },
  setChatState: () => {},
});

export function useApp() {
  return useContext(AppContext);
}

function AppInner() {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [manualSpaceId, setManualSpaceId] = useState<string | null>(null);
  const [chatState, setChatState] = useState<ChatState>({ messages: [], sessionId: null });
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  const checkSetup = useCallback(async () => {
    try {
      const status = await api.getSetupStatus();
      setNeedsSetup(status.needs_setup);
    } catch {
      setNeedsSetup(false);
    }
  }, []);

  const reload = useCallback(async () => {
    const s = await api.listSpaces();
    setSpaces(s);
  }, []);

  useEffect(() => {
    checkSetup();
    reload();
  }, [checkSetup, reload]);

  const urlSpaceId = useMemo(() => {
    const m = location.pathname.match(/\/space\/([a-z0-9]+)/);
    return m ? m[1] : null;
  }, [location.pathname]);

  useEffect(() => {
    if (urlSpaceId) setManualSpaceId(urlSpaceId);
  }, [urlSpaceId]);

  const selectedSpaceId = urlSpaceId || manualSpaceId;

  if (needsSetup === null) return null;

  if (needsSetup) {
    return (
      <WelcomeView onComplete={() => { setNeedsSetup(false); navigate("/chat", { replace: true }); }} />
    );
  }

  return (
    <AppContext.Provider value={{ spaces, selectedSpaceId, setSelectedSpaceId: setManualSpaceId, reload, chatState, setChatState }}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/inbox" element={<InboxView />} />
          <Route path="/chat" element={<ChatView />} />
          <Route path="/space/:spaceId" element={<Navigate to="flows" replace />} />
          <Route path="/space/:spaceId/flows" element={<SpaceFlowsView />} />
          <Route path="/space/:spaceId/flow/:flowId" element={<FlowDetailView />} />
          <Route path="/space/:spaceId/skills" element={<SkillsView />} />
          <Route path="/space/:spaceId/settings" element={<SpaceSettingsView />} />
          <Route path="/agents" element={<AgentsView />} />
          <Route path="/gateway" element={<GatewayView />} />
          <Route path="/connectors" element={<ToolsView />} />
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
