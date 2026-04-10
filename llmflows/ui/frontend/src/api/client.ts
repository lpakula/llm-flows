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

function del<T>(url: string) {
  return request<T>(url, { method: "DELETE" });
}

import type {
  Project,
  ProjectSettings,
  Task,
  TaskRun,
  Flow,
  AgentAlias,
  DaemonStatus,
  DaemonConfig,
  DashboardEntry,
  StepRunInfo,
  InboxResponse,
  AgentInfo,
  AgentConfigEntry,
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

  // Agent Aliases
  listAgentAliases: () => get<AgentAlias[]>("/api/agent-aliases"),
  createAgentAlias: (body: { name: string; agent: string; model: string }) =>
    post<AgentAlias>("/api/agent-aliases", body),
  updateAgentAlias: (id: string, body: Partial<AgentAlias>) =>
    patch<AgentAlias>(`/api/agent-aliases/${id}`, body),
  deleteAgentAlias: (id: string) => del<{ ok: boolean }>(`/api/agent-aliases/${id}`),

  // Attachments
  uploadAttachment: (taskId: string, file: File): Promise<{ url: string; filename: string }> => {
    const formData = new FormData();
    formData.append("file", file);
    return fetch(`/api/tasks/${taskId}/attachments`, { method: "POST", body: formData }).then((r) => {
      if (!r.ok) throw new Error(`Upload failed: ${r.status}`);
      return r.json();
    });
  },

  // Tasks
  listTasks: (projectId: string) => get<Task[]>(`/api/projects/${projectId}/tasks`),
  createTask: (projectId: string, body: { title: string; description: string; type: string; default_flow_name?: string }) =>
    post<Task>(`/api/projects/${projectId}/tasks`, body),
  updateTask: (id: string, body: Partial<{ title: string; description: string; default_flow_name: string; task_status: string; type: string }>) =>
    patch<Task>(`/api/tasks/${id}`, body),
  deleteTask: (id: string) => del<{ ok: boolean }>(`/api/tasks/${id}`),
  startTask: (
    id: string,
    body: {
      flow?: string | null;
      user_prompt: string;
      one_shot: boolean;
    },
  ) => post<Task>(`/api/tasks/${id}/start`, body),

  // Runs
  listTaskRuns: (taskId: string) => get<TaskRun[]>(`/api/tasks/${taskId}/runs`),
  stopRun: (runId: string) => post<{ ok: boolean; killed: boolean }>(`/api/runs/${runId}/stop`),
  pauseRun: (runId: string) => post<{ ok: boolean }>(`/api/runs/${runId}/pause`),
  resumeRun: (runId: string, prompt = "") => post<{ ok: boolean }>(`/api/runs/${runId}/resume`, { prompt }),
  completeStep: (stepRunId: string) => post<{ ok: boolean }>(`/api/step-runs/${stepRunId}/complete`),
  respondToStep: (stepRunId: string, response = "") => post<{ ok: boolean }>(`/api/step-runs/${stepRunId}/respond`, { response }),
  retryStep: (runId: string, stepName: string, prompt = "") => post<{ ok: boolean }>(`/api/runs/${runId}/retry-step`, { step_name: stepName, prompt }),
  deleteRun: (runId: string) => del<{ ok: boolean }>(`/api/runs/${runId}`),
  getRunSteps: (runId: string) => get<{ steps: StepRunInfo[] }>(`/api/runs/${runId}/steps`),

  // Inbox
  getInbox: () => get<InboxResponse>("/api/inbox"),
  archiveInboxItem: (itemId: string) => post<{ ok: boolean }>(`/api/inbox/${itemId}/archive`),

  // Queue
  getQueue: () => get<TaskRun[]>("/api/queue"),

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

};

import type { FlowStep } from "./types";
