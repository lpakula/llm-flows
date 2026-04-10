export interface Project {
  id: string;
  name: string;
  path: string;
  created_at: string;
}

export interface ProjectSettings {
  is_git_repo: boolean;
  max_concurrent_tasks: number;
  inbox_completed_runs: boolean;
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
  task_status: string;
  status: string;
  worktree_branch: string;
  worktree_path: string | null;
  agent_active: boolean;
  flow: string | null;
  current_step: string | null;
  run_id: string | null;
  run_count: number;
  last_run_status: string | null;
  last_run_outcome: string | null;
  last_run_started_at: string | null;
  last_run_completed_at: string | null;
  last_run_duration_seconds: number | null;
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
  duration_seconds: number | null;
  task_name?: string;
  project_name?: string;
  attachments?: { name: string; url: string }[];
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
  step_type: string;
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
  awaiting_user_at: string | null;
  duration_seconds: number | null;
  attempt: number;
  agent: string;
  model: string;
  gate_failures?: GateFailure[];
  user_response?: string;
  user_message?: string;
}

export interface StepRunInfo {
  name: string;
  flow: string;
  status: string;
  has_ifs: boolean;
  step_run: StepRunDetail | null;
  attempts?: StepRunDetail[];
  agent_alias?: string;
  step_type?: string;
  allow_max?: boolean;
  max_gate_retries?: number;
}

export interface InboxItem {
  inbox_id: string;
  step_run_id: string;
  step_name: string;
  step_type: "manual" | "prompt";
  step_position: number;
  task_id: string;
  task_name: string;
  task_description: string;
  project_id: string;
  project_name: string;
  run_id: string;
  flow_name: string;
  prompt: string;
  user_message: string;
  log_path: string;
  awaiting_since: string;
}

export interface CompletedRunItem {
  inbox_id: string;
  run_id: string;
  task_id: string;
  task_name: string;
  project_id: string;
  project_name: string;
  flow_name: string;
  outcome: string;
  summary: string;
  duration_seconds: number | null;
  completed_at: string;
  attachments?: { name: string; url: string }[];
}

export interface InboxResponse {
  awaiting: InboxItem[];
  completed: CompletedRunItem[];
  count: number;
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
