async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${options?.method || "GET"} ${url}: ${res.status}`);
  return res.json();
}

function get<T>(url: string) {
  return request<T>(url);
}

function post<T>(url: string, body?: unknown) {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function patch<T>(url: string, body: unknown) {
  return request<T>(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function put<T>(url: string, body?: unknown) {
  return request<T>(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function del<T>(url: string) {
  return request<T>(url, { method: "DELETE" });
}

import type {
  Space,
  SpaceSettings,
  FlowRun,
  Flow,
  FlowStep,
  FlowWarning,
  AgentAlias,
  DaemonStatus,
  DaemonConfig,
  DashboardEntry,
  StepRunInfo,
  InboxResponse,
  AgentInfo,
  AgentConfigEntry,
  ProviderInfo,
  GatewayConfig,
  ToolConfig,
  SkillInfo,
} from "./types";

export const api = {
  // Setup
  getSetupStatus: () => get<{ needs_setup: boolean; has_api_key: boolean; has_aliases: boolean }>("/api/setup-status"),

  configureProvider: (provider: string) =>
    post<{ ok: boolean }>(`/api/setup/configure-provider/${provider}`),
  validateAgentKey: (agent: string, key: string) =>
    post<{ valid: boolean; error?: string }>(`/api/agents/${agent}/validate-key`, { key }),

  // Dashboard
  getDashboard: () => get<DashboardEntry[]>("/api/dashboard"),

  // Spaces
  registerSpace: (path: string, name?: string) =>
    post<Space>("/api/spaces", { path, name: name || undefined }),
  browseDirs: (path?: string) =>
    get<{ current: string; parent: string | null; dirs: { name: string; path: string; has_git: boolean; has_flows: boolean }[] }>(
      `/api/browse-dirs${path ? `?path=${encodeURIComponent(path)}` : ""}`
    ),
  listSpaces: () => get<Space[]>("/api/spaces"),
  getSpace: (id: string) => get<Space>(`/api/spaces/${id}`),
  updateSpace: (id: string, body: Partial<{ name: string }>) =>
    patch<Space>(`/api/spaces/${id}`, body),
  deleteSpace: (id: string) => del<{ ok: boolean }>(`/api/spaces/${id}`),
  getSpaceSettings: (id: string) => get<SpaceSettings>(`/api/spaces/${id}/settings`),
  updateSpaceSettings: (id: string, body: Partial<SpaceSettings>) =>
    patch<SpaceSettings>(`/api/spaces/${id}/settings`, body),
  getFlowVariables: (flowId: string) =>
    get<Record<string, string>>(`/api/flows/${flowId}/variables`),
  setFlowVariable: (flowId: string, key: string, value: string) =>
    put<Record<string, string>>(`/api/flows/${flowId}/variables/${encodeURIComponent(key)}`, { value }),
  deleteFlowVariable: (flowId: string, key: string) =>
    del<Record<string, string>>(`/api/flows/${flowId}/variables/${encodeURIComponent(key)}`),

  // Agent Aliases (pre-defined, edit agent/model only)
  listAgentAliases: () => get<AgentAlias[]>("/api/agent-aliases"),
  updateAgentAlias: (id: string, body: { agent?: string; model?: string }) =>
    patch<AgentAlias>(`/api/agent-aliases/${id}`, body),

  // Scheduling
  scheduleFlow: (spaceId: string, flowId: string) =>
    post<FlowRun>(`/api/spaces/${spaceId}/schedule`, { flow_id: flowId }),

  // Flow Runs
  listFlowRuns: (spaceId: string) => get<FlowRun[]>(`/api/spaces/${spaceId}/runs`),
  listRunsByFlow: (flowId: string) => get<FlowRun[]>(`/api/flows/${flowId}/runs`),
  stopRun: (runId: string) => post<{ ok: boolean; killed: boolean }>(`/api/runs/${runId}/stop`),
  pauseRun: (runId: string) => post<{ ok: boolean }>(`/api/runs/${runId}/pause`),
  resumeRun: (runId: string, prompt = "") => post<{ ok: boolean }>(`/api/runs/${runId}/resume`, { prompt }),
  completeStep: (stepRunId: string) => post<{ ok: boolean }>(`/api/step-runs/${stepRunId}/complete`),
  respondToStep: (stepRunId: string, response = "") => post<{ ok: boolean }>(`/api/step-runs/${stepRunId}/respond`, { response }),
  deleteRun: (runId: string) => del<{ ok: boolean }>(`/api/runs/${runId}`),
  getRunSteps: (runId: string) => get<{ steps: StepRunInfo[] }>(`/api/runs/${runId}/steps`),

  // Inbox
  getInbox: () => get<InboxResponse>("/api/inbox"),
  archiveInboxItem: (itemId: string) => post<{ ok: boolean }>(`/api/inbox/${itemId}/archive`),

  // Queue
  getQueue: () => get<FlowRun[]>("/api/queue"),

  // Flows (space-scoped)
  listFlows: (spaceId: string) => get<Flow[]>(`/api/spaces/${spaceId}/flows`),
  getFlow: (id: string) => get<Flow>(`/api/flows/${id}`),
  createFlow: (spaceId: string, body: { name: string; description?: string; copy_from?: string }) =>
    post<Flow>(`/api/spaces/${spaceId}/flows`, body),
  updateFlow: (id: string, body: Partial<{ name: string; description: string; requirements: { tools: string[] }; max_concurrent_runs: number; max_spend_usd: number; starred: boolean; schedule_cron: string; schedule_timezone: string; schedule_enabled: boolean }>) =>
    patch<Flow>(`/api/flows/${id}`, body),
  validateFlow: (id: string) => get<{ warnings: FlowWarning[] }>(`/api/flows/${id}/validate`),
  deleteFlow: (id: string) => del<{ ok: boolean }>(`/api/flows/${id}`),
  addStep: (flowId: string, body: Record<string, unknown>) =>
    post<FlowStep>(`/api/flows/${flowId}/steps`, body),
  updateStep: (flowId: string, stepId: string, body: Record<string, unknown>) =>
    patch<FlowStep>(`/api/flows/${flowId}/steps/${stepId}`, body),
  deleteStep: (flowId: string, stepId: string) =>
    del<{ ok: boolean }>(`/api/flows/${flowId}/steps/${stepId}`),
  reorderSteps: (flowId: string, stepIds: string[]) =>
    post<Flow>(`/api/flows/${flowId}/reorder`, { step_ids: stepIds }),
  exportFlows: (spaceId: string) => post<unknown>(`/api/spaces/${spaceId}/flows/export`),
  importFlows: (spaceId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return fetch(`/api/spaces/${spaceId}/flows/import`, { method: "POST", body: formData }).then((r) => r.json());
  },

  // Skills
  listSkills: (spaceId: string) => get<SkillInfo[]>(`/api/spaces/${spaceId}/skills`),
  getSkillContent: (spaceId: string, name: string) => get<{ content: string }>(`/api/spaces/${spaceId}/skills/${encodeURIComponent(name)}/content`),

  // Daemon
  getDaemonStatus: () => get<DaemonStatus>("/api/daemon/status"),
  getDaemonLogs: (lines = 300) => get<{ lines: string[] }>(`/api/daemon/logs?lines=${lines}`),
  startDaemon: () => post<DaemonStatus & { ok: boolean }>("/api/daemon/start"),
  stopDaemon: () => post<DaemonStatus & { ok: boolean }>("/api/daemon/stop"),
  getDaemonConfig: () => get<DaemonConfig>("/api/config/daemon"),
  updateDaemonConfig: (body: Partial<DaemonConfig>) => patch<DaemonConfig>("/api/config/daemon", body),

  // Agents
  listAgents: () => get<string[]>("/api/agents"),
  getAgentsStatus: () => get<Record<string, AgentInfo>>("/api/agents/status"),
  getProvidersStatus: () => get<Record<string, ProviderInfo>>("/api/providers/status"),
  listModels: (agent?: string) =>
    get<string[]>(agent ? `/api/models?agent=${encodeURIComponent(agent)}` : "/api/models"),
  getAgentConfig: (agent: string) => get<AgentConfigEntry[]>(`/api/agents/${agent}/config`),
  setAgentConfig: (agent: string, key: string, value: string) =>
    post<AgentConfigEntry[]>(`/api/agents/${agent}/config`, { key, value }),
  deleteAgentConfig: (agent: string, configId: string) =>
    del<{ ok: boolean }>(`/api/agents/${agent}/config/${configId}`),

  // Gateway
  getGatewayConfig: () => get<GatewayConfig>("/api/config/gateway"),
  updateGatewayConfig: (body: Partial<GatewayConfig>) => patch<GatewayConfig>("/api/config/gateway", body),
  restartGateway: () => post<{ ok: boolean; message: string }>("/api/gateway/restart", {}),

  // Tools
  getToolsConfig: () => get<ToolConfig[]>("/api/config/tools"),
  updateToolConfig: (toolId: string, body: { enabled?: boolean; config?: Record<string, string> }) =>
    patch<ToolConfig>(`/api/config/tools/${toolId}`, body),

  // Chat
  sendChat: (message: string, spaceId?: string | null, sessionId?: string | null) =>
    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        space_id: spaceId || undefined,
        session_id: sessionId || undefined,
      }),
    }),
  deleteChatSession: (sessionId: string) => del<{ ok: boolean }>(`/api/chat/sessions/${sessionId}`),

};
