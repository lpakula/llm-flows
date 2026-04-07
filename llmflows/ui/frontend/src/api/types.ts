export interface Project {
  id: string;
  name: string;
  path: string;
  created_at: string;
}

export interface ProjectSettings {
  is_git_repo: boolean;
}

export interface AgentAlias {
  id: string;
  name: string;
  agent: string;
  model: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  project_id: string;
  name: string;
  description: string;
  type: string;
  default_flow_name: string | null;
  status: string;
  worktree_branch: string;
  worktree_path: string | null;
  agent_active: boolean;
  flow: string | null;
  current_step: string | null;
  run_id: string | null;
  run_count: number;
  created_at: string;
}

export interface TaskRun {
  id: string;
  task_id: string;
  project_id: string;
  flow_name: string | null;
  run_flow_id: string | null;
  current_step: string | null;
  status: string;
  outcome: string | null;
  summary: string | null;
  user_prompt: string;
  prompt: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  log_path: string | null;
  one_shot: boolean;
  paused_at: string | null;
  resume_prompt: string;
  task_name?: string;
  project_name?: string;
}

export interface Flow {
  id: string;
  project_id: string;
  name: string;
  description: string;
  step_count: number;
  steps: FlowStep[];
  created_at: string;
  updated_at: string;
}

export interface FlowStep {
  id: string;
  name: string;
  content: string;
  position: number;
  gates: Gate[];
  ifs: Gate[];
  agent_alias: string;
  allow_max: boolean;
  max_gate_retries: number;
}

export interface Gate {
  command: string;
  message: string;
}

export interface DaemonStatus {
  running: boolean;
  pid: number | null;
}

export interface DaemonConfig {
  poll_interval_seconds: number;
  run_timeout_minutes: number;
  gate_timeout_seconds: number;
}

export interface DashboardEntry {
  project: Project;
  task_counts: { running: number; queued: number; idle: number };
  queue_depth: number;
  active_runs: number;
  executing: { run: TaskRun; agent_active: boolean }[];
  recent_completions: TaskRun[];
}

export interface GateFailure {
  command: string;
  message: string;
  output?: string;
}

export interface StepRunDetail {
  id: string;
  status: string;
  prompt: string | null;
  started_at: string | null;
  completed_at: string | null;
  attempt: number;
  agent: string;
  model: string;
  gate_failures?: GateFailure[];
}

export interface StepRunInfo {
  name: string;
  flow: string;
  status: string;
  has_ifs: boolean;
  step_run: StepRunDetail | null;
  attempts?: StepRunDetail[];
  agent_alias?: string;
  allow_max?: boolean;
  max_gate_retries?: number;
}

export interface AgentInfo {
  label: string;
  available: boolean;
  binary: string;
  binary_path: string | null;
  command: string;
}

export interface AgentConfigEntry {
  id: string;
  agent: string;
  key: string;
  value: string;
}

export interface LogEntry {
  text?: string;
  cls?: string;
  type?: "output";
  lines?: string[];
  expanded?: boolean;
}
