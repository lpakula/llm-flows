export interface Space {
  id: string;
  name: string;
  path: string;
  created_at: string;
}

export interface SpaceSettings {
  max_concurrent_tasks: number;
}

export type StepType = "agent" | "code" | "shell" | "hitl";

export interface AgentAlias {
  id: string;
  name: string;
  type: "code" | "pi";
  agent: string;
  model: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface FlowRun {
  id: string;
  space_id: string;
  flow_id: string | null;
  flow_name: string | null;
  current_step: string | null;
  status: string;
  outcome: string | null;
  summary: string | null;
  prompt: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  log_path: string | null;
  paused_at: string | null;
  resume_prompt: string;
  duration_seconds: number | null;
  cost_usd: number | null;
  token_count: number | null;
  space_name?: string;
  attachments?: { name: string; url: string }[];
}

export interface FlowWarning {
  step_name: string;
  warning_type: string;
  message: string;
}

export interface FlowRequirements {
  tools: string[];
}

export interface Flow {
  id: string;
  space_id: string;
  name: string;
  description: string;
  requirements: FlowRequirements;
  variables: Record<string, string>;
  step_count: number;
  steps: FlowStep[];
  warnings?: FlowWarning[];
  max_concurrent_runs: number;
  max_spend_usd: number | null;
  starred?: boolean;
  schedule_cron: string | null;
  schedule_timezone: string;
  schedule_next_at: string | null;
  schedule_enabled: boolean;
  run_count?: number;
  total_cost_usd?: number;
  total_duration_seconds?: number | null;
  last_run_at?: string | null;
  active_run_count?: number;
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
  step_type: StepType;
  allow_max: boolean;
  max_gate_retries: number;
  skills: string[];
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
  summarizer_language: string;
}

export interface GatewayConfig {
  telegram_enabled: boolean;
  telegram_bot_token: string;
  telegram_allowed_chat_ids: number[];
  slack_enabled: boolean;
  slack_bot_token: string;
  slack_app_token: string;
  slack_allowed_channel_ids: string[];
}

export interface ToolConfigField {
  key: string;
  label: string;
  type: "select" | "secret" | "text";
  options?: { value: string; label: string; hint?: string }[];
  placeholder?: string;
  show_when?: Record<string, string>;
}

export interface ToolConfig {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  config: Record<string, string>;
  config_fields: ToolConfigField[];
}

export interface DashboardEntry {
  space: Space;
  run_counts: { running: number; queued: number };
  queue_depth: number;
  active_runs: number;
  executing: { run: FlowRun; agent_active: boolean }[];
  recent_completions: FlowRun[];
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
  cost_usd: number | null;
  token_count: number | null;
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
  step_type: "hitl";
  step_position: number;
  space_id: string;
  space_name: string;
  run_id: string;
  flow_id: string;
  flow_name: string;
  prompt: string;
  user_message: string;
  log_path: string;
  awaiting_since: string;
}

export interface CompletedRunItem {
  inbox_id: string;
  run_id: string;
  space_id: string;
  space_name: string;
  flow_id: string;
  flow_name: string;
  outcome: string;
  summary: string;
  duration_seconds: number | null;
  cost_usd: number | null;
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
  api_key_env: string;
  configured: boolean;
}

export interface ProviderInfo {
  label: string;
  api_key_env: string;
  configured: boolean;
  supports_tools: string[];
}

export interface AgentConfigEntry {
  id: string;
  agent: string;
  key: string;
  value: string;
}

export interface SkillInfo {
  name: string;
  path: string;
  description: string;
  compatibility: string;
}

export interface LogEntry {
  text?: string;
  cls?: string;
  type?: "output";
  lines?: string[];
  expanded?: boolean;
}

// --- Chat types ---

export type ChatEvent =
  | { type: "text_delta"; text: string }
  | { type: "thinking" }
  | { type: "done"; session_id: string };
