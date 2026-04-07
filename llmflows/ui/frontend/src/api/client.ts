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
  DaemonStatus,
  DaemonConfig,
  DashboardEntry,
  StepRunInfo,
  AgentInfo,
  Integration,
} from "./types";

export const api = {
  // Dashboard
  getDashboard: () => get<DashboardEntry[]>("/api/dashboard"),

  // Projects
  listProjects: () => get<Project[]>("/api/projects"),
  getProject: (id: string) => get<Project>(`/api/projects/${id}`),
  updateProject: (id: string, body: Partial<{ name: string; aliases: Record<string, unknown> }>) =>
    patch<Project>(`/api/projects/${id}`, body),
  deleteProject: (id: string) => del<{ ok: boolean }>(`/api/projects/${id}`),
  getProjectSettings: (id: string) => get<ProjectSettings>(`/api/projects/${id}/settings`),
  updateProjectSettings: (id: string, body: Partial<ProjectSettings>) =>
    patch<ProjectSettings>(`/api/projects/${id}/settings`, body),

  // Tasks
  listTasks: (projectId: string) => get<Task[]>(`/api/projects/${projectId}/tasks`),
  createTask: (projectId: string, body: { title: string; description: string; type: string }) =>
    post<Task>(`/api/projects/${projectId}/tasks`, body),
  updateTask: (id: string, body: Partial<{ title: string; description: string }>) =>
    patch<Task>(`/api/tasks/${id}`, body),
  deleteTask: (id: string) => del<{ ok: boolean }>(`/api/tasks/${id}`),
  startTask: (
    id: string,
    body: {
      flow: string;
      flow_chain: string[];
      user_prompt: string;
      model: string;
      agent: string;
      step_overrides: Record<string, unknown>;
      one_shot: boolean;
    },
  ) => post<Task>(`/api/tasks/${id}/start`, body),

  // Runs
  listTaskRuns: (taskId: string) => get<TaskRun[]>(`/api/tasks/${taskId}/runs`),
  stopRun: (runId: string) => post<{ ok: boolean; killed: boolean }>(`/api/runs/${runId}/stop`),
  deleteRun: (runId: string) => del<{ ok: boolean }>(`/api/runs/${runId}`),
  getRunSteps: (runId: string) => get<{ steps: StepRunInfo[] }>(`/api/runs/${runId}/steps`),

  // Queue / History
  getQueue: () => get<TaskRun[]>("/api/queue"),
  getHistory: (limit: number, offset: number) =>
    get<{ runs: TaskRun[]; total: number }>(`/api/history?limit=${limit}&offset=${offset}`),

  // Flows
  listFlows: () => get<Flow[]>("/api/flows"),
  getFlow: (id: string) => get<Flow>(`/api/flows/${id}`),
  createFlow: (body: { name: string; description?: string; copy_from?: string }) =>
    post<Flow>("/api/flows", body),
  updateFlow: (id: string, body: Partial<{ name: string; description: string }>) =>
    patch<Flow>(`/api/flows/${id}`, body),
  deleteFlow: (id: string) => del<{ ok: boolean }>(`/api/flows/${id}`),
  addStep: (flowId: string, body: { name: string; content: string; position?: number; gates?: unknown[]; ifs?: unknown[] }) =>
    post<FlowStep>(`/api/flows/${flowId}/steps`, body),
  updateStep: (flowId: string, stepId: string, body: Record<string, unknown>) =>
    patch<FlowStep>(`/api/flows/${flowId}/steps/${stepId}`, body),
  deleteStep: (flowId: string, stepId: string) =>
    del<{ ok: boolean }>(`/api/flows/${flowId}/steps/${stepId}`),
  reorderSteps: (flowId: string, stepIds: string[]) =>
    post<Flow>(`/api/flows/${flowId}/reorder`, { step_ids: stepIds }),
  exportFlows: () => post<unknown>("/api/flows/export"),
  importFlows: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return fetch("/api/flows/import", { method: "POST", body: formData }).then((r) => r.json());
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

  // GitHub / Integrations
  getGitHubStatus: () => get<{ available: boolean }>("/api/github/status"),
  getGitHubConfig: () =>
    get<{ has_token: boolean; masked_token: string; from_env: boolean }>("/api/config/github"),
  updateGitHubToken: (token: string) => patch<{ ok: boolean }>("/api/config/github", { token }),
  listIntegrations: (projectId: string) =>
    get<Integration[]>(`/api/projects/${projectId}/integrations`),
  createIntegration: (projectId: string, body: { provider: string; config: Record<string, unknown> }) =>
    post<Integration>(`/api/projects/${projectId}/integrations`, body),
  updateIntegration: (id: string, body: Partial<{ enabled: boolean; config: Record<string, unknown> }>) =>
    patch<Integration>(`/api/integrations/${id}`, body),
  deleteIntegration: (id: string) => del<{ ok: boolean }>(`/api/integrations/${id}`),
  detectRepo: (integrationId: string) =>
    post<{ repo: string; integration: Integration }>(`/api/integrations/${integrationId}/detect-repo`),
};

// Re-export FlowStep for the import
import type { FlowStep } from "./types";
