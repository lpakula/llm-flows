import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useApp } from "@/App";
import { useInterval } from "@/hooks/useInterval";
import { useLogStream } from "@/hooks/useEventSource";
import { LogViewer } from "@/components/LogViewer";
import { MarkdownContent } from "@/components/MarkdownContent";
import { AttachmentsGrid } from "@/components/AttachmentsGrid";
import { ImageLightbox } from "@/components/ImageLightbox";
import { StepModal } from "@/components/StepModal";
import type {
  Flow, FlowStep, FlowRun, FlowWarning, Gate, AgentAlias, SkillInfo,
  ConnectorConfig, StepRunInfo, GateFailure, FlowVersion,
} from "@/api/types";
import {
  statusBadge, displayStatus, formatSeconds, formatCost,
  stepBoxClass, stepConnectorClass,
} from "@/lib/format";
import { Play, UserCheck, Check, Circle, Clock, MessageCircle, RotateCcw } from "lucide-react";
import { marked } from "marked";
import { FlowChatWindow } from "@/views/Chat";

function shortDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function formatTimestamp(iso: string | undefined | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").toLocaleString();
  } catch { return iso; }
}

function systemStepLabel(name: string): string {
  if (name === "__post_run__") return "post-run analysis";
  return name;
}

function RunStatusIcon({ run }: { run: FlowRun }) {
  const label = displayStatus(run);
  if (label === "queued") return <Circle size={10} className="text-blue-400 fill-blue-400 shrink-0" />;
  if (label === "running" || label === "waiting")
    return <Circle size={10} className="text-yellow-400 fill-yellow-400 animate-pulse shrink-0" />;
  if (label === "completed") return <Circle size={10} className="text-green-400 fill-green-400 shrink-0" />;
  return <Circle size={10} className="text-red-400 fill-red-400 shrink-0" />;
}

export function FlowDetailView() {
  const { spaceId, flowId } = useParams<{ spaceId: string; flowId: string }>();
  const navigate = useNavigate();
  const { reload, setSelectedSpaceId } = useApp();

  const [flow, setFlow] = useState<Flow | null>(null);
  const [runs, setRuns] = useState<FlowRun[]>([]);
  const [aliases, setAliases] = useState<AgentAlias[]>([]);
  const [spaceSkills, setSpaceSkills] = useState<SkillInfo[]>([]);
  const [mcpConnectors, setMcpConnectors] = useState<ConnectorConfig[]>([]);

  // Inline editing
  const [editingName, setEditingName] = useState(false);
  const [editingDesc, setEditingDesc] = useState(false);
  const [nameValue, setNameValue] = useState("");
  const [descValue, setDescValue] = useState("");

  // Variables
  const [variables, setVariables] = useState<Record<string, { value: string; is_env: boolean }>>({});
  const [newVarKey, setNewVarKey] = useState("");
  const [newVarValue, setNewVarValue] = useState("");
  const [newVarEnv, setNewVarEnv] = useState(false);
  const [dirtyVarKeys, setDirtyVarKeys] = useState<Set<string>>(new Set());
  const [maxSpendValue, setMaxSpendValue] = useState("");

  // Step modal
  const [stepModal, setStepModal] = useState<{ mode: "add" | "edit"; step?: FlowStep } | null>(null);

  // Schedule
  const [schedCron, setSchedCron] = useState("");
  const [schedTz, setSchedTz] = useState("UTC");
  const [schedEnabled, setSchedEnabled] = useState(false);
  const [schedSaving, setSchedSaving] = useState(false);

  // Drag reorder
  const [localOrder, setLocalOrder] = useState<string[]>([]);
  const dragId = useRef<string | null>(null);
  const dragOverId = useRef<string | null>(null);

  // Run detail expansion
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [runSteps, setRunSteps] = useState<StepRunInfo[]>([]);
  const [logUrl, setLogUrl] = useState<string | null>(null);
  const [viewingStepName, setViewingStepName] = useState<string | null>(null);
  const [viewingStepPrompt, setViewingStepPrompt] = useState<string | null>(null);
  const [viewingStepAgentModel, setViewingStepAgentModel] = useState<{ agent: string; model: string } | null>(null);
  const [viewingStepDuration, setViewingStepDuration] = useState<number | null>(null);
  const [viewingStepCost, setViewingStepCost] = useState<number | null>(null);
  const [viewingStepResult, setViewingStepResult] = useState<string | null>(null);
  const [viewingGateFailures, setViewingGateFailures] = useState<GateFailure[]>([]);
  const [selectedAttempt, setSelectedAttempt] = useState<{ stepName: string; attemptId: string } | null>(null);
  const [respondText, setRespondText] = useState("");
  const [agentLogExpanded, setAgentLogExpanded] = useState(true);

  // Flow versions
  const [versions, setVersions] = useState<FlowVersion[]>([]);
  const [versionsOpen, setVersionsOpen] = useState(false);

  // Floating chat window
  const [chatOpen, setChatOpen] = useState(false);

  const { entries: logEntries, streaming } = useLogStream(logUrl, null);

  const loadRuns = useCallback(async () => {
    if (!flowId) return;
    const r = await api.listRunsByFlow(flowId);
    setRuns(r);
  }, [flowId]);

  const load = useCallback(async () => {
    if (!flowId) return;
    const [f, al, mc] = await Promise.all([
      api.getFlow(flowId),
      api.listAgentAliases(),
      api.getConnectors(),
    ]);
    setFlow(f);
    setSelectedSpaceId(f.space_id);
    setNameValue(f.name);
    setDescValue(f.description || "");
    setMaxSpendValue(f.max_spend_usd != null ? String(f.max_spend_usd) : "");
    setVariables(f.variables || {});
    setSchedCron(f.schedule_cron || "");
    setSchedTz(f.schedule_timezone || "UTC");
    setSchedEnabled(f.schedule_enabled || false);
    setAliases(al);
    setMcpConnectors(mc.filter((c) => c.enabled));
    setLocalOrder([...f.steps].sort((a, b) => a.position - b.position).map((s) => s.id));
    try {
      const sk = await api.listSkills(f.space_id);
      setSpaceSkills(sk);
    } catch { /* skills discovery may fail */ }
    try {
      const v = await api.listFlowVersions(flowId!);
      setVersions(v);
    } catch { /* versions may not exist yet */ }
  }, [flowId, setSelectedSpaceId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await load();
      if (!cancelled) await loadRuns();
    })();
    return () => { cancelled = true; };
  }, [load, loadRuns]);
  useInterval(loadRuns, 5000);

  const loadExpandedRun = useCallback(async () => {
    if (!expandedRunId) return;
    const data = await api.getRunSteps(expandedRunId);
    setRunSteps(data.steps);
  }, [expandedRunId]);

  useEffect(() => { loadExpandedRun(); }, [loadExpandedRun]);
  useInterval(loadExpandedRun, expandedRunId ? 5000 : null);

  // Save inline name
  const saveName = async () => {
    if (!flow || !nameValue.trim()) return;
    await api.updateFlow(flow.id, { name: nameValue.trim() });
    setEditingName(false);
    load();
    reload();
  };

  // Save inline description
  const saveDesc = async () => {
    if (!flow) return;
    await api.updateFlow(flow.id, { description: descValue });
    setEditingDesc(false);
    load();
  };

  // Variables
  const addVariable = async () => {
    if (!flow || !newVarKey.trim()) return;
    const updated = await api.setFlowVariable(flow.id, newVarKey.trim(), newVarValue, newVarEnv);
    setVariables(updated);
    setNewVarKey("");
    setNewVarValue("");
    setNewVarEnv(false);
    load();
  };

  const toggleVarEnv = (key: string) => {
    setVariables((v) => ({ ...v, [key]: { ...v[key], is_env: !v[key].is_env } }));
    setDirtyVarKeys((s) => new Set(s).add(key));
  };

  const saveVar = async (key: string) => {
    if (!flow) return;
    const cur = variables[key];
    if (!cur) return;
    await api.setFlowVariable(flow.id, key, cur.value, cur.is_env);
    setDirtyVarKeys((s) => { const n = new Set(s); n.delete(key); return n; });
  };

  const removeVariable = async (key: string) => {
    if (!flow) return;
    const updated = await api.deleteFlowVariable(flow.id, key);
    setVariables(updated);
    load();
  };

  // Schedule
  const saveSchedule = async (cron: string, tz: string, enabled: boolean) => {
    if (!flow) return;
    setSchedSaving(true);
    try {
      await api.updateFlow(flow.id, {
        schedule_cron: cron,
        schedule_timezone: tz,
        schedule_enabled: enabled,
      });
      load();
    } catch (e: unknown) {
      alert("Failed to save schedule: " + (e instanceof Error ? e.message : String(e)));
    }
    setSchedSaving(false);
  };

  const toggleScheduleEnabled = async () => {
    const next = !schedEnabled;
    setSchedEnabled(next);
    await saveSchedule(schedCron, schedTz, next);
  };

  // Steps
  const saveStep = async (data: { name: string; content: string; gates: Gate[]; ifs: Gate[];
    agent_alias: string; step_type: string; allow_max: boolean; max_gate_retries: number; skills: string[]; connectors: string[] }) => {
    if (!flow || !stepModal) return;
    if (stepModal.mode === "edit" && stepModal.step) {
      await api.updateStep(flow.id, stepModal.step.id, {
        name: data.name, content: data.content,
        gates: data.gates.filter((g) => g.command.trim()),
        ifs: data.ifs.filter((g) => g.command.trim()),
        agent_alias: data.agent_alias, step_type: data.step_type,
        allow_max: data.allow_max, max_gate_retries: data.max_gate_retries,
        skills: data.skills, connectors: data.connectors,
      });
    } else {
      await api.addStep(flow.id, {
        name: data.name, content: data.content,
        gates: data.gates.filter((g) => g.command.trim()),
        ifs: data.ifs.filter((g) => g.command.trim()),
        agent_alias: data.agent_alias, step_type: data.step_type,
        allow_max: data.allow_max, max_gate_retries: data.max_gate_retries,
        skills: data.skills, connectors: data.connectors,
      });
    }
    setStepModal(null);
    load();
  };

  const removeStep = async (stepId: string) => {
    if (!flow || !confirm("Remove this step?")) return;
    await api.deleteStep(flow.id, stepId);
    load();
  };

  const reorderSteps = async (ids: string[]) => {
    if (!flow) return;
    await api.reorderSteps(flow.id, ids);
    load();
  };

  // Run actions
  const [showRunVarsModal, setShowRunVarsModal] = useState(false);
  const [runVarValues, setRunVarValues] = useState<Record<string, string>>({});

  const handleRunClick = () => {
    if (!flow || !spaceId) return;
    if (hasEmptyVariables) {
      const initial: Record<string, string> = {};
      for (const [k, v] of Object.entries(variables)) {
        if (!v.value) initial[k] = "";
      }
      setRunVarValues(initial);
      setShowRunVarsModal(true);
    } else {
      scheduleRun();
    }
  };

  const scheduleRun = async (overrides?: Record<string, string>) => {
    if (!flow || !spaceId) return;
    try {
      await api.scheduleFlow(spaceId, flow.id, overrides);
      await loadRuns();
    } catch (e: unknown) {
      alert("Failed to schedule: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const stopRun = async (runId: string) => {
    await api.stopRun(runId);
    loadRuns();
  };

  const replayRun = async (run: FlowRun) => {
    if (!flow || !spaceId) return;
    try {
      const overrides = run.run_variables && Object.keys(run.run_variables).length > 0
        ? run.run_variables
        : undefined;
      await api.scheduleFlow(spaceId, flow.id, overrides);
      await loadRuns();
    } catch (e: unknown) {
      alert("Failed to replay: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const deleteRun = async (runId: string) => {
    await api.deleteRun(runId);
    if (expandedRunId === runId) collapseRunDetail();
    loadRuns();
  };

  const deleteFlow = async () => {
    if (!flow || !confirm(`Delete flow "${flow.name}"?`)) return;
    try {
      await api.deleteFlow(flow.id);
      reload();
      navigate(`/space/${spaceId}/flows`);
    } catch (e: unknown) {
      alert("Error: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const exportFlow = async () => {
    if (!flow) return;
    try {
      const result = await api.exportFlowToDisk(flow.id);
      alert(`Exported to ${result.path}`);
    } catch (e: unknown) {
      alert("Export failed: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const rollbackToVersion = async (versionId: string, versionNum: number) => {
    if (!flow || !confirm(`Rollback to version ${versionNum}? The current version will be saved automatically.`)) return;
    try {
      await api.rollbackFlow(flow.id, versionId);
      load();
      reload();
    } catch (e: unknown) {
      alert("Rollback failed: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const duplicateFlow = async () => {
    if (!flow) return;
    const newName = prompt("Name for the copy:", flow.name + "-copy");
    if (!newName) return;
    try {
      const created = await api.createFlow(flow.space_id, { name: newName, copy_from: flow.name });
      reload();
      navigate(`/space/${flow.space_id}/flow/${created.id}`);
    } catch (e: unknown) {
      alert("Error: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  // Expanded run detail
  const expandRun = async (runId: string) => {
    if (expandedRunId === runId) {
      collapseRunDetail();
      return;
    }
    setExpandedRunId(runId);
    setLogUrl(null);
    setViewingStepName(null);
    setSelectedAttempt(null);
    setViewingGateFailures([]);
    const data = await api.getRunSteps(runId);
    setRunSteps(data.steps);
    const activeStep = data.steps.find(
      (s) => s.step_run && (s.status === "running" || s.status === "awaiting_user"),
    );
    if (activeStep?.step_run) {
      setLogUrl(`/api/step-runs/${activeStep.step_run.id}/logs`);
      setViewingStepName(systemStepLabel(activeStep.name));
      setViewingStepPrompt(activeStep.step_run.prompt || null);
      setViewingStepAgentModel({ agent: activeStep.step_run.agent || "", model: activeStep.step_run.model || "" });
      setViewingStepDuration(activeStep.step_run.duration_seconds ?? null);
      setViewingStepCost(activeStep.step_run.cost_usd ?? null);
      setViewingStepResult(activeStep.step_run.step_result || null);
    }
  };

  const collapseRunDetail = () => {
    setExpandedRunId(null);
    setRunSteps([]);
    setLogUrl(null);
    setViewingStepName(null);
    setViewingStepPrompt(null);
    setViewingStepAgentModel(null);
    setViewingStepDuration(null);
    setViewingStepCost(null);
    setViewingStepResult(null);
    setSelectedAttempt(null);
    setViewingGateFailures([]);
    setAgentLogExpanded(true);
  };

  const respondToStep = async (stepRunId: string, response: string) => {
    await api.respondToStep(stepRunId, response);
    setRespondText("");
    loadExpandedRun();
  };

  const hasEmptyVariables = Object.entries(variables).some(([, v]) => !v.value);
  const stepMap = flow ? Object.fromEntries(flow.steps.map((s) => [s.id, s])) : {};
  const sortedSteps = localOrder.map((id) => stepMap[id]).filter(Boolean) as FlowStep[];
  const expandedRun = runs.find((r) => r.id === expandedRunId) || null;
  const expandedRunIsActive = expandedRun ? !!expandedRun.started_at && !expandedRun.completed_at : false;

  if (!flow) {
    return <div className="flex-1 overflow-y-auto p-6 text-gray-500">Loading...</div>;
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* Back */}
      <button
        onClick={() => navigate(`/space/${spaceId}/flows`)}
        className="text-xs text-gray-500 hover:text-gray-300 mb-4 block"
      >
        &larr; Flows
      </button>

      {/* Flow header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          {editingName ? (
            <div className="flex items-center gap-2">
              <input value={nameValue} onChange={(e) => setNameValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && saveName()}
                autoFocus
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-lg font-semibold text-white focus:outline-none focus:ring-2 focus:ring-blue-500 w-64" />
              <button onClick={saveName} className="text-xs text-blue-400 hover:text-blue-300">Save</button>
              <button onClick={() => { setEditingName(false); setNameValue(flow.name); }}
                className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
            </div>
          ) : (
            <h2
              className="text-xl font-semibold text-white cursor-pointer hover:text-blue-300 transition"
              onClick={() => setEditingName(true)}
              title="Click to edit"
            >
              {flow.name}
            </h2>
          )}
          {editingDesc ? (
            <div className="flex items-center gap-2 mt-1">
              <input value={descValue} onChange={(e) => setDescValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && saveDesc()}
                autoFocus placeholder="Description"
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-sm text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500 w-full" />
              <button onClick={saveDesc} className="text-xs text-blue-400 hover:text-blue-300">Save</button>
              <button onClick={() => { setEditingDesc(false); setDescValue(flow.description || ""); }}
                className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
            </div>
          ) : (
            <p
              className="text-sm text-gray-400 mt-1 cursor-pointer hover:text-gray-200 transition min-h-[20px]"
              onClick={() => setEditingDesc(true)}
              title="Click to edit"
            >
              {flow.description || "Add description..."}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3 ml-4 shrink-0">
          <button onClick={exportFlow} className="text-xs text-gray-400 hover:text-gray-200">Export</button>
          <button onClick={deleteFlow} className="text-xs text-red-500 hover:text-red-400">Delete</button>
        </div>
      </div>

      {/* Warnings (excluding missing_variable — handled by run modal) */}
      {flow.warnings && flow.warnings.filter((w: FlowWarning) => w.warning_type !== "missing_variable").length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-5 py-3 mb-4">
          <h4 className="text-sm font-semibold text-amber-400 mb-2">Configuration Warnings</h4>
          <ul className="space-y-1">
            {flow.warnings.filter((w: FlowWarning) => w.warning_type !== "missing_variable").map((w: FlowWarning, i: number) => (
              <li key={i} className="text-xs text-amber-300/80">
                {w.step_name && <span className="text-amber-400 font-mono mr-1">{w.step_name}:</span>}
                {w.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Settings: two-column layout */}
      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* Left: Variables, Tools, Limits */}
        <div className="space-y-6">
          {/* Variables */}
          <div>
            <h3 className="text-sm font-medium text-gray-200 mb-1">Variables</h3>
            <p className="text-xs text-gray-500 mb-3">
              Define key-value pairs to use in step content as <code className="text-gray-400">{"{{flow.KEY}}"}</code>. Empty variables will be prompted at run time. <br />Toggle <code className="text-gray-400">ENV</code> to also inject as an environment variable at agent runtime. 
            </p>
            <div className="space-y-2">
              {Object.entries(variables).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => (
                <div key={key} className="flex items-start gap-2">
                  <span className="text-xs font-mono text-cyan-400 w-32 shrink-0 truncate pt-1" title={key}>{key}</span>
                  <textarea
                    value={entry.value}
                    onChange={(e) => {
                      setVariables((v) => ({ ...v, [key]: { ...v[key], value: e.target.value } }));
                      setDirtyVarKeys((s) => new Set(s).add(key));
                      e.target.style.height = "auto";
                      e.target.style.height = e.target.scrollHeight + "px";
                    }}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveVar(key); } }}
                    ref={(el) => { if (el) { el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; } }}
                    rows={1}
                    className="w-1/2 max-w-xs bg-gray-800 border border-gray-700 rounded px-2.5 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none max-h-32 overflow-hidden focus:overflow-y-auto"
                    placeholder="value"
                  />
                  <button
                    onClick={() => toggleVarEnv(key)}
                    className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium border transition-colors ${
                      entry.is_env
                        ? "bg-emerald-900/40 border-emerald-700/60 text-emerald-400"
                        : "bg-gray-800 border-gray-700 text-gray-600 hover:text-gray-400 hover:border-gray-600"
                    }`}
                    title="Inject as environment variable at runtime"
                  >ENV</button>
                  {dirtyVarKeys.has(key) && (
                    <button onClick={() => saveVar(key)}
                      className="text-xs text-blue-400 hover:text-blue-300 shrink-0">Save</button>
                  )}
                  <button onClick={() => removeVariable(key)}
                    className="text-xs text-red-400/60 hover:text-red-400 shrink-0">x</button>
                </div>
              ))}
          <div className="flex items-center gap-2">
            <input value={newVarKey} onChange={(e) => setNewVarKey(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addVariable()}
              placeholder="NEW_KEY" className="w-32 bg-gray-800 border border-gray-700 rounded px-2.5 py-1 text-xs font-mono placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500" />
            <input value={newVarValue} onChange={(e) => setNewVarValue(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addVariable()}
              placeholder="value" className="w-1/2 max-w-xs bg-gray-800 border border-gray-700 rounded px-2.5 py-1 text-xs font-mono placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500" />
            <button
              onClick={() => setNewVarEnv((v) => !v)}
              className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium border transition-colors ${
                newVarEnv
                  ? "bg-emerald-900/40 border-emerald-700/60 text-emerald-400"
                  : "bg-gray-800 border-gray-700 text-gray-600 hover:text-gray-400 hover:border-gray-600"
              }`}
              title="Inject as environment variable at runtime"
            >ENV</button>
          </div>
          <button onClick={addVariable} disabled={!newVarKey.trim()}
            className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300">+ Add</button>
            </div>
          </div>

          {/* Limits */}
          <div className="flex gap-8">
            <div>
              <h3 className="text-sm font-medium text-gray-200 mb-1">Max Spend per Run</h3>
              <p className="text-xs text-gray-500 mb-3">
                Runs exceeding this cost will be cancelled. Leave empty for no limit.
              </p>
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-400">$</span>
                <input
                  type="text"
                  inputMode="decimal"
                  placeholder="No limit"
                  value={maxSpendValue}
                  onChange={(e) => setMaxSpendValue(e.target.value)}
                  onBlur={async () => {
                    const val = parseFloat(maxSpendValue);
                    await api.updateFlow(flow.id, { max_spend_usd: isNaN(val) || val <= 0 ? 0 : val });
                    load();
                  }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                  className="w-24 bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-200 mb-1">Max Concurrent Runs</h3>
              <p className="text-xs text-gray-500 mb-3">
                How many runs of this flow can execute in parallel.
              </p>
              <input
                type="number"
                min={1}
                value={flow.max_concurrent_runs ?? 1}
                onChange={async (e) => {
                  const val = Math.max(1, parseInt(e.target.value) || 1);
                  await api.updateFlow(flow.id, { max_concurrent_runs: val });
                  load();
                }}
                className="w-20 bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Right: Schedule */}
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h3 className="text-sm font-medium text-gray-200">Schedule</h3>
            <button
              onClick={() => {
                const next = !schedEnabled;
                setSchedEnabled(next);
                if (!next) saveSchedule(schedCron, schedTz, false);
              }}
              disabled={schedSaving || (hasEmptyVariables && !schedEnabled)}
              title={hasEmptyVariables && !schedEnabled ? "Fill in all variables before enabling schedule" : undefined}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors flex-shrink-0 ${
                schedEnabled ? "bg-blue-500" : "bg-gray-700"
              } ${hasEmptyVariables && !schedEnabled ? "opacity-40 cursor-not-allowed" : ""}`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                  schedEnabled ? "translate-x-[18px]" : "translate-x-[3px]"
                }`}
              />
            </button>
            {schedEnabled && flow.schedule_next_at && (
              <span className="text-xs text-gray-500">Next run: {shortDateTime(flow.schedule_next_at)}</span>
            )}
          </div>
          <p className="text-xs text-gray-500 mb-3">
            {hasEmptyVariables
              ? "Fill in all variable values to enable scheduling."
              : "Automatically run this flow on a recurring schedule. The daemon will enqueue a run when it's due."}
          </p>
          <div className={`flex flex-wrap gap-1.5 mb-3 ${!schedEnabled ? "opacity-40 pointer-events-none" : ""}`}>
            {[
              { label: "Every hour", cron: "0 * * * *" },
              { label: "Every 6h", cron: "0 */6 * * *" },
              { label: "Daily 9am", cron: "0 9 * * *" },
              { label: "Daily 2pm", cron: "0 14 * * *" },
              { label: "Mon-Fri 9am", cron: "0 9 * * 1-5" },
              { label: "Weekly Mon", cron: "0 9 * * 1" },
              { label: "Weekend 9am", cron: "0 9 * * 0,6" },
            ].map((p) => (
              <button
                key={p.cron}
                onClick={() => { setSchedCron(p.cron); saveSchedule(p.cron, schedTz, true); }}
                className={`px-2 py-1 rounded text-[10px] border transition ${
                  schedEnabled && schedCron === p.cron
                    ? "bg-blue-500/20 text-blue-300 border-blue-500/40"
                    : "border-gray-700 text-gray-500 hover:border-gray-500 hover:text-gray-300"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className={`flex items-center gap-3 ${!schedEnabled ? "opacity-40 pointer-events-none" : ""}`}>
            <input
              value={schedEnabled ? schedCron : ""}
              onChange={(e) => setSchedCron(e.target.value)}
              onBlur={() => { if (schedCron !== (flow.schedule_cron || "")) saveSchedule(schedCron, schedTz, true); }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
              placeholder="0 14 * * *"
              disabled={!schedEnabled}
              className="w-40 bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-xs font-mono text-gray-200 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed"
            />
            <select
              value={schedTz}
              onChange={(e) => { setSchedTz(e.target.value); saveSchedule(schedCron, e.target.value, true); }}
              disabled={!schedEnabled}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed"
            >
              {[
                "UTC",
                "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
                "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Warsaw",
                "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata",
                "Australia/Sydney",
              ].map((tz) => (
                <option key={tz} value={tz}>{tz}</option>
              ))}
            </select>
            {schedSaving && <span className="text-[10px] text-gray-500">Saving...</span>}
          </div>
        </div>
      </div>

      {/* Version History */}
      {versions.length > 0 && (
        <div className="mb-4">
          <button
            onClick={() => setVersionsOpen(!versionsOpen)}
            className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-200 mb-2"
          >
            <RotateCcw size={12} />
            <span>Version History ({versions.length}) &middot; Current: v{flow.version || 1}</span>
            <span className="text-[10px]">{versionsOpen ? "▲" : "▼"}</span>
          </button>
          {versionsOpen && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="divide-y divide-gray-800">
                {versions.map((v) => (
                  <div key={v.id} className="px-4 py-2.5 flex items-center justify-between hover:bg-gray-800/30">
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-mono text-gray-300">v{v.version}</span>
                      {v.description && (
                        <span className="text-xs text-gray-500 truncate max-w-md">{v.description}</span>
                      )}
                      <span className="text-[10px] text-gray-600">{shortDateTime(v.created_at)}</span>
                    </div>
                    <button
                      onClick={() => rollbackToVersion(v.id, v.version)}
                      className="text-xs text-blue-400 hover:text-blue-300"
                    >Rollback</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Steps + Runs split */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        {/* Steps panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-800 flex items-center justify-between">
            <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
              Steps ({sortedSteps.length})
            </span>
            <button onClick={() => setStepModal({ mode: "add" })}
              className="text-xs text-blue-400 hover:text-blue-300">+ Add Step</button>
          </div>
          <div className="divide-y divide-gray-800">
            {sortedSteps.map((step, i) => (
              <div
                key={step.id}
                className="px-4 py-2.5 flex items-start gap-2 hover:bg-gray-800/30 transition"
                onDragOver={(e) => {
                  e.preventDefault();
                  if (dragOverId.current !== step.id) {
                    dragOverId.current = step.id;
                    if (dragId.current && dragId.current !== step.id) {
                      setLocalOrder((prev) => {
                        const next = [...prev];
                        const from = next.indexOf(dragId.current!);
                        const to = next.indexOf(step.id);
                        if (from === -1 || to === -1) return prev;
                        next.splice(from, 1);
                        next.splice(to, 0, dragId.current!);
                        return next;
                      });
                    }
                  }
                }}
              >
                <div
                  draggable
                  onDragStart={() => { dragId.current = step.id; dragOverId.current = step.id; }}
                  onDragEnd={() => { reorderSteps(localOrder); dragId.current = null; dragOverId.current = null; }}
                  className="mt-0.5 shrink-0 cursor-grab active:cursor-grabbing text-gray-600 hover:text-gray-400 select-none text-xs"
                  title="Drag to reorder"
                >⠿</div>
                <span className="text-[10px] text-gray-600 font-mono w-4 shrink-0 mt-0.5">{i + 1}</span>
                <div className="flex-1 min-w-0 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm font-medium text-white truncate">{step.name}</span>
                    <span className={`text-[10px] shrink-0 ${
                      step.step_type === "code" ? "text-blue-400" :
                      step.step_type === "hitl" ? "text-amber-400" : "text-gray-500"
                    }`}>{step.step_type || "agent"}</span>
                    {step.agent_alias && (
                      <span className="text-[10px] text-cyan-400 shrink-0">{step.agent_alias}</span>
                    )}
                    {step.gates && step.gates.length > 0 && (
                      <span className="text-[10px] text-yellow-400 shrink-0">
                        {step.gates.length} {step.gates.length === 1 ? "gate" : "gates"}
                      </span>
                    )}
                    {step.ifs && step.ifs.length > 0 && (
                      <span className="text-[10px] text-purple-400 shrink-0">
                        {step.ifs.length} {step.ifs.length === 1 ? "if" : "ifs"}
                      </span>
                    )}
                    {step.skills && step.skills.length > 0 && (
                      <span className="text-[10px] text-pink-400 shrink-0">
                        {step.skills.length} {step.skills.length === 1 ? "skill" : "skills"}
                      </span>
                    )}
                    {step.connectors && step.connectors.length > 0 && (
                      <span className="text-[10px] text-emerald-400 shrink-0">
                        {step.connectors.length} {step.connectors.length === 1 ? "connector" : "connectors"}
                      </span>
                    )}
                    {flow.warnings?.some((w: FlowWarning) => w.step_name === step.name && w.warning_type !== "missing_variable") && (
                      <span className="text-[10px] text-amber-400 shrink-0" title="Has warnings">⚠</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button onClick={() => setStepModal({ mode: "edit", step })}
                      className="text-xs text-gray-500 hover:text-blue-400 transition">Edit</button>
                    <button onClick={() => removeStep(step.id)}
                      className="text-xs text-gray-500 hover:text-red-400 transition">Delete</button>
                  </div>
                </div>
              </div>
            ))}
            {sortedSteps.length === 0 && (
              <div className="text-gray-500 text-center py-6 text-xs">No steps yet</div>
            )}
          </div>
        </div>

        {/* Runs panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-800 flex items-center justify-between">
            <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
              Runs ({runs.length})
            </span>
            <button
              onClick={handleRunClick}
              title="Start a new run"
              className="bg-blue-600 hover:bg-blue-500 text-white text-xs px-3 py-1 rounded-lg transition inline-flex items-center gap-1"
            >
              <Play size={10} /> Run
            </button>
          </div>
          <div className="divide-y divide-gray-800 max-h-[400px] overflow-y-auto">
            {runs.map((run) => {
              const dur = run.duration_seconds != null ? formatSeconds(run.duration_seconds) : null;
              const isExpanded = expandedRunId === run.id;
              return (
                <div
                  key={run.id}
                  onClick={() => expandRun(run.id)}
                  className={`px-4 py-2 flex items-center gap-3 cursor-pointer transition hover:bg-gray-800/40 ${
                    isExpanded ? "bg-gray-800/60" : ""
                  }`}
                >
                  <RunStatusIcon run={run} />
                  <span className="text-xs text-gray-500 font-mono">{run.id}</span>
                  <span className="text-[10px] text-gray-600 tabular-nums">{shortDateTime(run.started_at || run.created_at)}</span>
                  {dur && <span className="text-[10px] text-gray-400 tabular-nums flex items-center gap-0.5"><Clock size={9} className="opacity-50" />{dur}</span>}
                  {run.cost_usd != null && run.cost_usd > 0 && (
                    <span className="text-[10px] text-emerald-400 tabular-nums">{formatCost(run.cost_usd)}</span>
                  )}
                  <div className="ml-auto flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    {(!!run.started_at && !run.completed_at) && (
                      <button onClick={() => stopRun(run.id)} className="text-[10px] text-red-400 hover:text-red-300">Stop</button>
                    )}
                    {run.completed_at && run.outcome && run.outcome !== "completed" && (
                      <button onClick={() => replayRun(run)}
                        title="Replay with same variables"
                        className="text-[10px] text-gray-600 hover:text-blue-400 inline-flex items-center gap-0.5">
                        <RotateCcw size={9} /> Replay
                      </button>
                    )}
                    {(run.completed_at || !run.started_at) && (
                      <button onClick={() => deleteRun(run.id)} className="text-[10px] text-gray-600 hover:text-red-400">Delete</button>
                    )}
                  </div>
                </div>
              );
            })}
            {runs.length === 0 && (
              <div className="text-gray-500 text-center py-6 text-xs">No runs yet</div>
            )}
          </div>
        </div>
      </div>

      {/* Expanded run detail */}
      {expandedRun && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden mb-4">
          <div className="px-5 py-3 border-b border-gray-800 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">Run {expandedRun.id}</span>
              <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${statusBadge(displayStatus(expandedRun))}`}>
                {displayStatus(expandedRun)}
              </span>
            </div>
            <div className="flex items-center gap-3">
              {expandedRunIsActive && (
                <button onClick={() => stopRun(expandedRun.id)}
                  className="text-xs text-red-400 hover:text-red-300">Force Stop</button>
              )}
              {expandedRun.completed_at && expandedRun.outcome && expandedRun.outcome !== "completed" && (
                <button onClick={() => replayRun(expandedRun)}
                  className="text-xs text-gray-500 hover:text-blue-400 inline-flex items-center gap-1">
                  <RotateCcw size={11} /> Replay
                </button>
              )}
              <button onClick={collapseRunDetail} className="text-xs text-gray-500 hover:text-gray-300">Close</button>
            </div>
          </div>

          {/* Run metadata */}
          <div className="px-5 py-3 flex flex-wrap gap-x-6 gap-y-2 border-b border-gray-800">
            <div className="flex flex-col gap-0.5">
              <span className="text-[10px] uppercase tracking-wide text-gray-600 font-medium">Started</span>
              <span className="text-sm text-gray-400 tabular-nums">{formatTimestamp(expandedRun.started_at)}</span>
            </div>
            {expandedRun.completed_at && (
              <div className="flex flex-col gap-0.5">
                <span className="text-[10px] uppercase tracking-wide text-gray-600 font-medium">Completed</span>
                <span className="text-sm text-gray-400 tabular-nums">{formatTimestamp(expandedRun.completed_at)}</span>
              </div>
            )}
            {expandedRun.duration_seconds != null && (
              <div className="flex flex-col gap-0.5">
                <span className="text-[10px] uppercase tracking-wide text-gray-600 font-medium">Duration</span>
                <span className="text-sm text-gray-400 tabular-nums">{formatSeconds(expandedRun.duration_seconds)}</span>
              </div>
            )}
            {expandedRun.cost_usd != null && expandedRun.cost_usd > 0 && (
              <div className="flex flex-col gap-0.5">
                <span className="text-[10px] uppercase tracking-wide text-gray-600 font-medium">Cost</span>
                <span className="text-sm text-gray-400 tabular-nums">{formatCost(expandedRun.cost_usd)}</span>
              </div>
            )}
          </div>

          {/* Step pipeline */}
          {runSteps.length > 0 && (
            <div className="px-5 py-3 border-b border-gray-800">
              <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-2">Steps</div>
              <div className="flex items-center overflow-x-auto pb-1">
                {runSteps.map((step, i) => {
                  const attempts = step.attempts || [];
                  const stepLabel = systemStepLabel(step.name);
                  const isCancelled = displayStatus(expandedRun) === "cancelled";
                  const resolveStatus = (s: string) =>
                    isCancelled && s === "pending" ? "skipped" : s;
                  const attemptStatus = (att: typeof attempts[number], idx: number) =>
                    resolveStatus(idx < attempts.length - 1 ? "failed" : att.status);
                  return (
                    <div key={i} className="flex items-center">
                      {i > 0 && <div className={`w-5 h-0.5 ${stepConnectorClass(resolveStatus(step.status))}`} />}
                      <button
                        onClick={() => {
                          if (!attempts[0]) return;
                          const first = attempts[0];
                          setLogUrl(`/api/step-runs/${first.id}/logs`);
                          setViewingStepName(stepLabel);
                          setSelectedAttempt(attempts.length > 1 ? { stepName: step.name, attemptId: first.id } : null);
                          setViewingStepPrompt(first.prompt || null);
                          setViewingStepAgentModel({ agent: first.agent || "", model: first.model || "" });
                          setViewingStepDuration(first.duration_seconds ?? null);
                          setViewingStepCost(first.cost_usd ?? null);
                          setViewingStepResult(first.step_result || null);
                          setViewingGateFailures(attempts[1]?.gate_failures || []);
                        }}
                        className={`px-3 py-1.5 rounded-md text-xs whitespace-nowrap ${stepBoxClass(attempts.length ? attemptStatus(attempts[0], 0) : resolveStatus(step.status))} ${
                          viewingStepName === stepLabel && (!selectedAttempt || selectedAttempt.attemptId === attempts[0]?.id)
                            ? "border-2" : "border"
                        } ${attempts[0] ? "cursor-pointer hover:opacity-80" : "cursor-default"}`}
                      >
                        {step.step_type === "hitl" && <UserCheck size={10} className="inline mr-1 -mt-px opacity-60" />}
                        <span className={resolveStatus(step.status) === "skipped" ? "line-through" : ""}>{stepLabel}</span>
                      </button>
                      {attempts.slice(1).map((att, j) => (
                        <div key={att.id} className="flex items-center gap-1">
                          <div className="w-3 h-0.5 bg-orange-800" />
                          <button
                            onClick={() => {
                              setLogUrl(`/api/step-runs/${att.id}/logs`);
                              setViewingStepName(`${stepLabel} #${j + 2}`);
                              setSelectedAttempt({ stepName: step.name, attemptId: att.id });
                              setViewingStepPrompt(att.prompt || null);
                              setViewingStepAgentModel({ agent: att.agent || "", model: att.model || "" });
                              setViewingStepDuration(att.duration_seconds ?? null);
                              setViewingStepCost(att.cost_usd ?? null);
                              setViewingStepResult(att.step_result || null);
                              setViewingGateFailures(attempts[j + 2]?.gate_failures || []);
                            }}
                            className={`px-1.5 py-1 rounded text-[10px] whitespace-nowrap cursor-pointer hover:opacity-80 ${
                              selectedAttempt?.attemptId === att.id
                                ? "border-2 " + stepBoxClass(attemptStatus(att, j + 1))
                                : "border " + stepBoxClass(attemptStatus(att, j + 1))
                            }`}
                          >↻</button>
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Awaiting user */}
          {(() => {
            const awaitingStep = runSteps.find((s) => s.status === "awaiting_user" && s.step_run);
            if (!awaitingStep?.step_run) return null;
            const stepLabel = systemStepLabel(awaitingStep.name);
            return (
              <div className="px-5 py-3 border-b border-gray-800 bg-amber-950/10">
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                  <span className="text-xs font-medium text-amber-400">Awaiting input: {stepLabel}</span>
                </div>
                {awaitingStep.step_run!.user_message && (
                  <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mb-3 max-h-64 overflow-y-auto">
                    <MarkdownContent text={awaitingStep.step_run!.user_message} className="text-sm text-gray-300" />
                  </div>
                )}
                <div className="space-y-2">
                  <textarea
                    value={respondText}
                    onChange={(e) => setRespondText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey && respondText.trim()) {
                        e.preventDefault();
                        respondToStep(awaitingStep.step_run!.id, respondText);
                      }
                    }}
                    placeholder="Type your response..."
                    rows={1}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-600 resize-none overflow-hidden"
                    onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; }}
                  />
                  <div className="flex items-center gap-3">
                    <button onClick={() => respondToStep(awaitingStep.step_run!.id, respondText)}
                      disabled={!respondText.trim()}
                      className="inline-flex items-center gap-1 px-2 py-1 text-green-500 hover:text-green-400 disabled:opacity-40 text-xs font-medium">
                      <Check size={12} /> Submit
                    </button>
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Log viewer */}
          {viewingStepName && (
            <div className="border-b border-gray-800">
              <div className="px-5 py-2 flex items-center justify-between border-b border-gray-800/80">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                  <span className="text-[10px] uppercase tracking-wide text-gray-500 truncate">
                    Step: <span className="text-gray-200 font-mono normal-case">{viewingStepName}</span>
                  </span>
                </div>
                <button onClick={() => {
                  setLogUrl(null); setViewingStepName(null); setViewingStepPrompt(null);
                  setViewingStepAgentModel(null); setViewingStepDuration(null); setViewingStepCost(null);
                  setViewingStepResult(null); setSelectedAttempt(null); setViewingGateFailures([]); setAgentLogExpanded(true);
                }} className="text-xs text-gray-500 hover:text-gray-300">Close</button>
              </div>
              {viewingStepAgentModel && (
                <div className="px-5 py-2 border-b border-gray-800/80">
                  <span className="text-[10px] uppercase tracking-wide text-gray-500">
                    MODEL: <span className="text-gray-200 font-mono normal-case">{viewingStepAgentModel.model?.includes("/") ? viewingStepAgentModel.model : `${viewingStepAgentModel.agent || "—"}/${viewingStepAgentModel.model || "—"}`}</span>
                  </span>
                </div>
              )}
              {(viewingStepDuration != null || viewingStepCost != null) && (
                <div className="px-5 py-2 border-b border-gray-800/80">
                  <span className="text-[10px] uppercase tracking-wide text-gray-500">
                    {viewingStepDuration != null && (<>DURATION: <span className="text-gray-200 font-mono normal-case">{formatSeconds(viewingStepDuration)}</span></>)}
                    {viewingStepCost != null && (<>{viewingStepDuration != null && <span className="mx-2 text-gray-700">·</span>}COST: <span className="text-gray-200 font-mono normal-case">{formatCost(viewingStepCost)}</span></>)}
                  </span>
                </div>
              )}
              {viewingStepPrompt && (
                <div className="border-b border-gray-800/80">
                  <details className="group [&_summary::-webkit-details-marker]:hidden px-5 py-3">
                    <summary className="text-[10px] uppercase tracking-wide text-gray-600 cursor-pointer select-none list-none inline-flex items-center gap-2">
                      <span className="text-gray-700 group-open:rotate-90 transition-transform inline-block text-[9px]">▶</span>
                      Injected context
                    </summary>
                    <pre className="mt-2 text-gray-500 text-[11px] whitespace-pre-wrap font-mono bg-gray-900 border border-gray-800 rounded-lg p-3 max-h-64 overflow-y-auto">{viewingStepPrompt}</pre>
                  </details>
                </div>
              )}
              {viewingGateFailures.length > 0 && (
                <div className="border-b border-gray-800/80">
                  <details className="group [&_summary::-webkit-details-marker]:hidden px-5 py-3" open>
                    <summary className="text-[10px] uppercase tracking-wide text-orange-600 cursor-pointer select-none list-none inline-flex items-center gap-2">
                      <span className="text-orange-700 group-open:rotate-90 transition-transform inline-block text-[9px]">▶</span>
                      Gate failures ({viewingGateFailures.length})
                    </summary>
                    <div className="mt-1 space-y-1.5">
                      {viewingGateFailures.map((gf, i) => (
                        <div key={i} className="bg-red-900/20 border border-red-900/50 rounded-lg p-2 text-[11px]">
                          <code className="font-mono text-red-400 break-all">{gf.command}</code>
                          <div className="text-gray-400 mt-0.5">{gf.message}</div>
                          {gf.output && <pre className="text-gray-500 mt-1 text-[10px] whitespace-pre-wrap break-all">{gf.output}</pre>}
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              )}
              <div className={agentLogExpanded ? "h-80 min-h-0" : "min-h-0"}>
                <LogViewer entries={logEntries} streaming={streaming} onExpandedChange={setAgentLogExpanded} />
              </div>

              {viewingStepResult && (
                <div className="border-t border-gray-800/80">
                  <details className="group [&_summary::-webkit-details-marker]:hidden px-5 py-3">
                    <summary className="text-[10px] uppercase tracking-wide text-gray-600 cursor-pointer select-none list-none inline-flex items-center gap-2">
                      <span className="text-gray-700 group-open:rotate-90 transition-transform inline-block text-[9px]">▶</span>
                      Result
                    </summary>
                    <pre className="mt-2 text-gray-500 text-[11px] whitespace-pre-wrap font-mono bg-gray-900 border border-gray-800 rounded-lg p-3 max-h-64 overflow-y-auto">{viewingStepResult}</pre>
                  </details>
                </div>
              )}
            </div>
          )}

          {/* Inbox */}
          {expandedRun.inbox_message ? (
            <RunSummarySection summary={expandedRun.inbox_message} attachments={expandedRun.attachments || []} label="Inbox" />
          ) : expandedRun.attachments && expandedRun.attachments.length > 0 ? (
            <RunSummarySection summary="" attachments={expandedRun.attachments} label="Attachments" />
          ) : null}
        </div>
      )}

      {/* Step modal */}
      {stepModal && (
        <StepModal
          title={stepModal.mode === "edit" ? `Edit Step: ${stepModal.step?.name}` : "Add Step"}
          initialData={
            stepModal.mode === "edit" && stepModal.step
              ? {
                  name: stepModal.step.name,
                  content: stepModal.step.content || "",
                  gates: (stepModal.step.gates || []).map((g) => ({ ...g })),
                  ifs: (stepModal.step.ifs || []).map((g) => ({ ...g })),
                  agent_alias: stepModal.step.agent_alias || "normal",
                  step_type: stepModal.step.step_type || "agent",
                  allow_max: stepModal.step.allow_max || false,
                  max_gate_retries: stepModal.step.max_gate_retries ?? 3,
                  skills: stepModal.step.skills || [],
                  connectors: stepModal.step.connectors || [],
                }
              : {
                  name: "", content: "", gates: [], ifs: [],
                  agent_alias: "normal", step_type: "agent",
                  allow_max: false, max_gate_retries: 3, skills: [],
                  connectors: [],
                }
          }
          aliases={aliases}
          skills={spaceSkills}
          mcpConnectors={mcpConnectors}
          onSave={saveStep}
          onClose={() => setStepModal(null)}
        />
      )}

      {/* Floating chat toggle */}
      <button
        onClick={() => setChatOpen((v) => !v)}
        className={`fixed bottom-6 right-6 z-40 rounded-full p-3 shadow-lg transition-all duration-200 ${
          chatOpen
            ? "bg-gray-700 hover:bg-gray-600 text-gray-300"
            : "bg-blue-600 hover:bg-blue-500 text-white"
        }`}
        title={chatOpen ? "Close AI assistant" : "Ask AI about this flow"}
      >
        <MessageCircle size={18} />
      </button>

      {/* Floating chat window */}
      {spaceId && (
        <FlowChatWindow
          spaceId={spaceId}
          flowId={flow.id}
          flowName={flow.name}
          open={chatOpen}
          onClose={() => setChatOpen(false)}
        />
      )}

      {/* Run variables modal */}
      {showRunVarsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowRunVarsModal(false)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-5 w-full max-w-sm shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-gray-200 mb-3">Set variables for this run</h3>
            <div className="space-y-3">
              {Object.keys(runVarValues).map((key) => (
                <div key={key}>
                  <label className="block text-xs text-gray-400 mb-1">{key}</label>
                  <textarea
                    value={runVarValues[key]}
                    onChange={(e) => {
                      setRunVarValues((prev) => ({ ...prev, [key]: e.target.value }));
                      e.target.style.height = "auto";
                      e.target.style.height = e.target.scrollHeight + "px";
                    }}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); const allFilled = Object.values({ ...runVarValues, [key]: e.currentTarget.value }).every(Boolean); if (allFilled) { setShowRunVarsModal(false); scheduleRun({ ...runVarValues, [key]: e.currentTarget.value }); } } }}
                    autoFocus={Object.keys(runVarValues)[0] === key}
                    rows={1}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500 resize-none max-h-32 overflow-hidden focus:overflow-y-auto"
                    placeholder={`Enter ${key}…`}
                  />
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setShowRunVarsModal(false)}
                className="text-xs text-gray-400 hover:text-gray-200 px-3 py-1.5 rounded-lg transition"
              >Cancel</button>
              <button
                onClick={() => { setShowRunVarsModal(false); scheduleRun(runVarValues); }}
                disabled={Object.values(runVarValues).some((v) => !v.trim())}
                className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs px-4 py-1.5 rounded-lg transition inline-flex items-center gap-1"
              >
                <Play size={10} /> Run
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

function RunSummarySection({ summary, attachments, label = "Summary" }: { summary: string; attachments: { name: string; url: string }[]; label?: string }) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const html = summary ? marked.parse(summary) as string : "";
  const proseClass =
    "prose prose-invert max-w-none text-gray-400 text-sm leading-relaxed " +
    "[&_h1]:text-base [&_h1]:font-bold [&_h1]:text-gray-300 [&_h1]:mt-4 [&_h1]:mb-2 " +
    "[&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-gray-300 [&_h2]:mt-3 [&_h2]:mb-1.5 " +
    "[&_p]:my-1.5 [&_p]:text-gray-400 " +
    "[&_ul]:my-1.5 [&_ul]:pl-4 [&_ul]:space-y-0.5 " +
    "[&_ol]:my-1.5 [&_ol]:pl-4 [&_ol]:space-y-0.5 " +
    "[&_code]:bg-gray-800 [&_code]:text-gray-300 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[11px] " +
    "[&_pre]:bg-gray-800 [&_pre]:border [&_pre]:border-gray-700 [&_pre]:rounded-lg [&_pre]:p-3 [&_pre]:my-2 [&_pre]:overflow-x-auto " +
    "[&_pre_code]:bg-transparent [&_pre_code]:text-gray-400 [&_pre_code]:p-0 [&_pre_code]:text-[11px] " +
    "[&_strong]:text-gray-300 [&_strong]:font-semibold " +
    "[&_a]:text-blue-400 [&_a]:underline " +
    "[&_img]:max-w-[180px] [&_img]:max-h-[120px] [&_img]:object-contain [&_img]:rounded-md [&_img]:border [&_img]:border-gray-700 [&_img]:cursor-zoom-in [&_img]:inline-block [&_img]:mr-2 [&_img]:my-1";
  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.tagName === "IMG") { e.preventDefault(); setLightboxSrc((target as HTMLImageElement).src); }
  };
  return (
    <div className="px-5 py-3">
      <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-1">{label}</div>
      <div className={proseClass} onClick={handleClick}>
        {html && <div dangerouslySetInnerHTML={{ __html: html }} />}
        <AttachmentsGrid files={attachments} />
      </div>
      {lightboxSrc && <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />}
    </div>
  );
}
