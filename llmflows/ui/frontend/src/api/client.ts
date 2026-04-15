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
  Project,
  ProjectSettings,
  FlowRun,
  Flow,
  FlowStep,
  AgentAlias,
  DaemonStatus,
  DaemonConfig,
  DashboardEntry,
  StepRunInfo,
  InboxResponse,
  AgentInfo,
  AgentConfigEntry,
  GatewayConfig,
  SkillInfo,
} from "./types";

export const api = {
  // Dashboard
  getDashboard: () => get<DashboardEntry[]>("/api/dashboard"),

  // Projects
  listProjects: () => get<Project[]>("/api/projects"),
  getProject: (id: string) => get<Project>(`/api/projects/${id}`),
  updateProject: (id: string, body: Partial<{ name: string }>) =>
    patch<Project>(`/api/projects/${id}`, body),
  deleteProject: (id: string) => del<{ ok: boolean }>(`/api/projects/${id}`),
  getProjectSettings: (id: string) => get<ProjectSettings>(`/api/projects/${id}/settings`),
  updateProjectSettings: (id: string, body: Partial<ProjectSettings>) =>
    patch<ProjectSettings>(`/api/projects/${id}/settings`, body),
  getProjectVariables: (id: string) =>
    get<Record<string, string>>(`/api/projects/${id}/variables`),
  setProjectVariable: (id: string, key: string, value: string) =>
    put<Record<string, string>>(`/api/projects/${id}/variables/${encodeURIComponent(key)}`, { value }),
  deleteProjectVariable: (id: string, key: string) =>
    del<Record<string, string>>(`/api/projects/${id}/variables/${encodeURIComponent(key)}`),

  // Agent Aliases
  listAgentAliases: () => get<AgentAlias[]>("/api/agent-aliases"),
  createAgentAlias: (body: { name: string; agent: string; model: string }) =>
    post<AgentAlias>("/api/agent-aliases", body),
  updateAgentAlias: (id: string, body: Partial<AgentAlias>) =>
    patch<AgentAlias>(`/api/agent-aliases/${id}`, body),
  deleteAgentAlias: (id: string) => del<{ ok: boolean }>(`/api/agent-aliases/${id}`),

  // Scheduling
  scheduleFlow: (projectId: string, flowId: string, oneShot = false) =>
    post<FlowRun>(`/api/projects/${projectId}/schedule`, { flow_id: flowId, one_shot: oneShot }),

  // Flow Runs
  listFlowRuns: (projectId: string) => get<FlowRun[]>(`/api/projects/${projectId}/runs`),
  stopRun: (runId: string) => post<{ ok: boolean; killed: boolean }>(`/api/runs/${runId}/stop`),
  pauseRun: (runId: string) => post<{ ok: boolean }>(`/api/runs/${runId}/pause`),
  resumeRun: (runId: string, prompt = "") => post<{ ok: boolean }>(`/api/runs/${runId}/resume`, { prompt }),
  completeStep: (stepRunId: string) => post<{ ok: boolean }>(`/api/step-runs/${stepRunId}/complete`),
  respondToStep: (stepRunId: string, response = "") => post<{ ok: boolean }>(`/api/step-runs/${stepRunId}/respond`, { response }),
  retryStep: (runId: string, stepName: string) => post<{ ok: boolean }>(`/api/runs/${runId}/retry-step`, { step_name: stepName }),
  deleteRun: (runId: string) => del<{ ok: boolean }>(`/api/runs/${runId}`),
  getRunSteps: (runId: string) => get<{ steps: StepRunInfo[] }>(`/api/runs/${runId}/steps`),

  // Inbox
  getInbox: () => get<InboxResponse>("/api/inbox"),
  archiveInboxItem: (itemId: string) => post<{ ok: boolean }>(`/api/inbox/${itemId}/archive`),

  // Queue
  getQueue: () => get<FlowRun[]>("/api/queue"),

  // Flows (project-scoped)
  listFlows: (projectId: string) => get<Flow[]>(`/api/projects/${projectId}/flows`),
  getFlow: (id: string) => get<Flow>(`/api/flows/${id}`),
  createFlow: (projectId: string, body: { name: string; description?: string; copy_from?: string }) =>
    post<Flow>(`/api/projects/${projectId}/flows`, body),
  updateFlow: (id: string, body: Partial<{ name: string; description: string }>) =>
    patch<Flow>(`/api/flows/${id}`, body),
  deleteFlow: (id: string) => del<{ ok: boolean }>(`/api/flows/${id}`),
  addStep: (flowId: string, body: Record<string, unknown>) =>
    post<FlowStep>(`/api/flows/${flowId}/steps`, body),
  updateStep: (flowId: string, stepId: string, body: Record<string, unknown>) =>
    patch<FlowStep>(`/api/flows/${flowId}/steps/${stepId}`, body),
  deleteStep: (flowId: string, stepId: string) =>
    del<{ ok: boolean }>(`/api/flows/${flowId}/steps/${stepId}`),
  reorderSteps: (flowId: string, stepIds: string[]) =>
    post<Flow>(`/api/flows/${flowId}/reorder`, { step_ids: stepIds }),
  exportFlows: (projectId: string) => post<unknown>(`/api/projects/${projectId}/flows/export`),
  importFlows: (projectId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return fetch(`/api/projects/${projectId}/flows/import`, { method: "POST", body: formData }).then((r) => r.json());
  },

  // Skills
  listSkills: (projectId: string) => get<SkillInfo[]>(`/api/projects/${projectId}/skills`),
  getSkillContent: (projectId: string, name: string) => get<{ content: string }>(`/api/projects/${projectId}/skills/${encodeURIComponent(name)}/content`),

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

};
