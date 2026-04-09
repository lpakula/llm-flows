import { useState, useEffect, useCallback, Fragment } from "react";
import { useAutoResize } from "@/hooks/useAutoResize";
import { useImagePaste } from "@/hooks/useImagePaste";
import type { ReactNode } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { useLogStream } from "@/hooks/useEventSource";
import { useApp } from "@/App";
import { LogViewer } from "@/components/LogViewer";
import { RunModal } from "@/components/RunModal";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { Task, TaskRun, StepRunInfo, Flow, GateFailure } from "@/api/types";
import { statusBadge, displayStatus, duration, stepBoxClass, stepConnectorClass, statusDot } from "@/lib/format";
import { marked } from "marked";

const DESC_PREVIEW_LINES = 4;

function formatTaskTimestamp(iso: string | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").toLocaleString();
  } catch {
    return iso;
  }
}

function truncateOneLine(text: string, maxChars: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= maxChars) return t;
  return t.slice(0, maxChars - 1) + "…";
}

export function TaskView() {
  const { projectId, taskId } = useParams<{ projectId: string; taskId: string }>();
  const navigate = useNavigate();
  const { projects } = useApp();

  const [task, setTask] = useState<Task | null>(null);
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [runSteps, setRunSteps] = useState<Record<string, StepRunInfo[]>>({});
  const [logUrl, setLogUrl] = useState<string | null>(null);
  const [viewingStepName, setViewingStepName] = useState<string | null>(null);

  const [runModal, setRunModal] = useState(false);
  const [flows, setFlows] = useState<Flow[]>([]);


  // Retry modal
  const [retryModal, setRetryModal] = useState<{ runId: string; stepName: string } | null>(null);
  const [retryPrompt, setRetryPrompt] = useState("");

  // Selected attempt for viewing logs
  const [selectedAttempt, setSelectedAttempt] = useState<{ stepName: string; attemptId: string } | null>(null);
  const [viewingStepPrompt, setViewingStepPrompt] = useState<string | null>(null);
  const [viewingStepAgentModel, setViewingStepAgentModel] = useState<{ agent: string; model: string } | null>(null);
  const [viewingGateFailures, setViewingGateFailures] = useState<GateFailure[]>([]);
  const [agentLogExpanded, setAgentLogExpanded] = useState(true);

  // Description editing
  const [editingDesc, setEditingDesc] = useState(false);
  const [editDescText, setEditDescText] = useState("");
  const editDescRef = useAutoResize(editDescText);
  const onEditDescPaste = useImagePaste(task?.id, setEditDescText);
  const [descExpanded, setDescExpanded] = useState(false);

  const worktreePrefix = task?.worktree_path ? task.worktree_path + "/" : null;
  const { entries: logEntries, streaming } = useLogStream(logUrl, worktreePrefix);

  const isRunActive = (run: TaskRun) => !!run.started_at && !run.completed_at;

  const loadTask = useCallback(async () => {
    if (!taskId) return;
    try {
      for (const p of projects) {
        const ts = await api.listTasks(p.id);
        const found = ts.find((t) => t.id === taskId);
        if (found) {
          setTask(found);
          const r = await api.listTaskRuns(taskId);
          setRuns(r);
          if (expandedRun) {
            const data = await api.getRunSteps(expandedRun);
            setRunSteps((prev) => ({ ...prev, [expandedRun]: data.steps }));
          }
          return;
        }
      }
    } catch (e) {
      console.error("Task load error:", e);
    }
  }, [taskId, projects, expandedRun]);

  useEffect(() => {
    const load = async () => {
      if (!taskId) return;
      for (const p of projects) {
        const ts = await api.listTasks(p.id);
        const found = ts.find((t) => t.id === taskId);
        if (found) {
          setTask(found);
          const r = await api.listTaskRuns(taskId);
          setRuns(r);
          const fl = await api.listFlows(found.project_id);
          setFlows(fl);
          const activeRun = r.find((run) => isRunActive(run));
          if (activeRun) {
            setExpandedRun(activeRun.id);
            const data = await api.getRunSteps(activeRun.id);
            setRunSteps((prev) => ({ ...prev, [activeRun.id]: data.steps }));
            const steps = data.steps;
            const activeStep = steps.find((s) => s.step_run && s.status === "running");
            if (activeStep?.step_run) {
              setLogUrl(`/api/step-runs/${activeStep.step_run.id}/logs`);
              const stepLabel =
                activeStep.name === "__summary__"
                  ? "summary"
                  : activeStep.name === "__one_shot__"
                    ? "one-shot"
                    : activeStep.name;
              setViewingStepName(stepLabel);
              setViewingStepPrompt(activeStep.step_run.prompt || null);
              setViewingStepAgentModel({
                agent: activeStep.step_run.agent || "",
                model: activeStep.step_run.model || "",
              });
            }
          }
          return;
        }
      }
    };
    load();
  }, [taskId, projects]);

  useInterval(loadTask, 5000);

  const loadRunSteps = async (runId: string) => {
    const data = await api.getRunSteps(runId);
    setRunSteps((prev) => ({ ...prev, [runId]: data.steps }));
  };

  const toggleRun = (runId: string) => {
    if (expandedRun === runId) {
      setExpandedRun(null);
      setLogUrl(null);
      setViewingStepName(null);
      setSelectedAttempt(null);
      setViewingStepPrompt(null);
      setViewingStepAgentModel(null);
      setViewingGateFailures([]);
      setAgentLogExpanded(true);
    } else {
      setExpandedRun(runId);
      setLogUrl(null);
      setViewingStepName(null);
      setSelectedAttempt(null);
      setViewingStepPrompt(null);
      setViewingStepAgentModel(null);
      setViewingGateFailures([]);
      setAgentLogExpanded(true);
      loadRunSteps(runId);
      const run = runs.find((r) => r.id === runId);
      if (run && isRunActive(run)) {
        const steps = runSteps[runId] || [];
        const activeStep = steps.find((s) => s.step_run && s.status === "running");
        if (activeStep?.step_run) {
          viewStepLogs(activeStep);
        }
      }
    }
  };

  const viewStepLogs = (step: StepRunInfo) => {
    if (!step.step_run) return;
    setLogUrl(`/api/step-runs/${step.step_run.id}/logs`);
    const name = step.name === "__summary__" ? "summary" : step.name === "__one_shot__" ? "one-shot" : step.name;
    setViewingStepName(name);
    setViewingStepPrompt(step.step_run.prompt || null);
    setViewingStepAgentModel({
      agent: step.step_run.agent || "",
      model: step.step_run.model || "",
    });
    setViewingGateFailures(step.step_run.gate_failures || []);
  };

  const forceStopRun = async (runId: string) => {
    if (!confirm("Force stop this run? The agent process will be killed.")) return;
    await api.stopRun(runId);
    setLogUrl(null);
    if (taskId) {
      setRuns(await api.listTaskRuns(taskId));
    }
  };

  const completeStep = async (stepRunId: string) => {
    if (!confirm("Mark this step as manually completed?")) return;
    await api.completeStep(stepRunId);
    if (expandedRun) loadRunSteps(expandedRun);
  };

  const openRetryModal = (runId: string, stepName: string) => {
    setRetryPrompt("");
    setRetryModal({ runId, stepName });
  };

  const submitRetry = async () => {
    if (!retryModal) return;
    const { runId, stepName } = retryModal;
    setRetryModal(null);
    setLogUrl(null);
    setViewingStepName(null);
    setViewingStepPrompt(null);
    setViewingStepAgentModel(null);
    setSelectedAttempt(null);
    setViewingGateFailures([]);
    setAgentLogExpanded(true);
    await api.retryStep(runId, stepName, retryPrompt);
    if (taskId) setRuns(await api.listTaskRuns(taskId));
    await loadRunSteps(runId);
  };

  const deleteRun = async (runId: string) => {
    if (!confirm("Delete this run?")) return;
    await api.deleteRun(runId);
    if (expandedRun === runId) {
      setExpandedRun(null);
      setLogUrl(null);
    }
    if (taskId) {
      setRuns(await api.listTaskRuns(taskId));
    }
  };

  const openRunModal = async () => {
    if (!task) return;
    if (flows.length === 0) {
      const fl = await api.listFlows(task.project_id);
      setFlows(fl);
    }
    setRunModal(true);
  };

  const updateField = async (field: string, value: string) => {
    if (!task) return;
    const body: Record<string, string> = { [field]: value };
    const updated = await api.updateTask(task.id, body);
    setTask(updated);
  };

  const submitRunModal = async (_taskId: string, { flow, prompt, one_shot }: { flow: string; prompt: string; one_shot: boolean }) => {
    if (!task) return;
    await api.startTask(task.id, { flow: flow || null, user_prompt: prompt, one_shot });
    setRuns(await api.listTaskRuns(task.id));
  };

  const saveDescription = async () => {
    if (!task) return;
    const updated = await api.updateTask(task.id, { description: editDescText });
    setTask(updated);
    setEditingDesc(false);
  };

  const headlineRun =
    runs.find((r) => isRunActive(r)) || runs.find((r) => !r.completed_at) || null;
  const descPlain = (task?.description || "").trim();
  const descLines = descPlain ? descPlain.split("\n") : [];
  const descNeedsClamp =
    !editingDesc &&
    descPlain.length > 0 &&
    (descLines.length > DESC_PREVIEW_LINES || descPlain.length > 320);

  return (
    <div className="flex-1 overflow-y-auto">

      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        <button
          onClick={() => (task ? navigate(`/project/${task.project_id}`) : navigate("/"))}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          &larr; Back
        </button>
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2 gap-y-1">
            <h1 className="text-xl font-semibold text-white tracking-tight">{task?.name || "Loading..."}</h1>
            {headlineRun && (
              <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${statusBadge(displayStatus(headlineRun))}`}>
                {displayStatus(headlineRun)}
              </span>
            )}
            {task?.agent_active ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-gray-400">
                <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                Agent active
              </span>
            ) : null}
          </div>

          {task && !editingDesc ? (
            <div className="mt-3">
              {descPlain ? (
                <div className={!descExpanded && descNeedsClamp ? "line-clamp-4 overflow-hidden" : ""}>
                  <MarkdownContent text={task.description} />
                </div>
              ) : (
                <p className="text-sm italic text-gray-600">No description</p>
              )}
              <div className="flex flex-wrap items-center gap-3 mt-2 mb-4">
                {descNeedsClamp ? (
                  <button
                    type="button"
                    onClick={() => setDescExpanded((e) => !e)}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    {descExpanded ? "Show less" : "Show more"}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    setEditDescText(task.description || "");
                    setEditingDesc(true);
                  }}
                  className="text-xs text-gray-600 hover:text-gray-300"
                >
                  Edit description
                </button>
              </div>
            </div>
          ) : null}
          {task && editingDesc ? (
            <div className="mt-3 space-y-2">
              <textarea
                ref={editDescRef}
                value={editDescText}
                onChange={(e) => setEditDescText(e.target.value)}
                onPaste={onEditDescPaste}
                rows={4}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none overflow-hidden"
                autoFocus
              />
              <div className="flex gap-2">
                <button type="button" onClick={saveDescription} className="text-xs text-blue-400 hover:text-blue-300">
                  Save
                </button>
                <button type="button" onClick={() => setEditingDesc(false)} className="text-xs text-gray-500 hover:text-gray-300">
                  Cancel
                </button>
              </div>
            </div>
          ) : null}

          {/* Properties */}
          {task ? (
            <div className="mt-8 mb-4 flex flex-wrap gap-x-6 gap-y-3">
              <PropField label="ID">
                <span className="text-sm font-mono text-gray-400">{task.id}</span>
              </PropField>

              <PropField label="Status">
                <select
                  value={task.task_status}
                  onChange={(e) => updateField("task_status", e.target.value)}
                  className="bg-transparent text-sm text-gray-300 focus:outline-none cursor-pointer hover:text-white"
                >
                  <option value="backlog">Backlog</option>
                  <option value="queue">Queue</option>
                  <option value="in_progress">In Progress</option>
                  <option value="completed">Completed</option>
                </select>
              </PropField>

              <PropField label="Type">
                <select
                  value={task.type}
                  onChange={(e) => updateField("type", e.target.value)}
                  className="bg-transparent text-sm text-gray-300 focus:outline-none cursor-pointer hover:text-white capitalize"
                >
                  <option value="feature">Feature</option>
                  <option value="fix">Fix</option>
                  <option value="refactor">Refactor</option>
                  <option value="chore">Chore</option>
                </select>
              </PropField>

              <PropField label="Default Flow">
                <select
                  value={task.default_flow_name ?? ""}
                  onChange={(e) => updateField("default_flow_name", e.target.value)}
                  className="bg-transparent text-sm text-gray-300 focus:outline-none cursor-pointer hover:text-white"
                >
                  <option value="">None</option>
                  {flows.map((f) => (
                    <option key={f.id} value={f.name}>{f.name}</option>
                  ))}
                </select>
              </PropField>

              {task.worktree_branch ? (
                <PropField label="Branch">
                  <span className="text-sm font-mono text-gray-400">{task.worktree_branch}</span>
                </PropField>
              ) : null}

              <PropField label="Created">
                <span className="text-sm text-gray-400 tabular-nums">{formatTaskTimestamp(task.created_at)}</span>
              </PropField>

            </div>
          ) : null}
        </div>
      </header>

      {/* Runs */}
      <div className="p-6">
        <div className="flex items-center justify-between gap-3 mb-4">
          <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
            Runs ({runs.length})
          </h3>
          <button
            type="button"
            onClick={openRunModal}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition"
          >
            + New Run
          </button>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full table-fixed text-left text-xs min-w-[640px]">
              <colgroup>
                <col className="w-[140px]" />
                <col className="w-[120px]" />
                <col className="w-[240px]" />
                <col className="w-[88px]" />
                <col className="w-[150px]" />
                <col className="w-[120px]" />
              </colgroup>
              <thead>
                <tr className="border-b border-gray-800 text-[10px] uppercase tracking-wide text-gray-600">
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Flow</th>
                  <th className="px-4 py-2.5 font-medium">Prompt</th>
                  <th className="px-4 py-2.5 font-medium">Duration</th>
                  <th className="px-4 py-2.5 font-medium">Date</th>
                  <th className="px-4 py-2.5 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-gray-600">
                      No runs yet. Start one with <span className="text-blue-400">+ New Run</span>.
                    </td>
                  </tr>
                ) : (
                  runs.map((run) => (
                    <Fragment key={run.id}>
                      <tr
                        className="border-b border-gray-800/80 hover:bg-gray-800/40 cursor-pointer transition-colors"
                        onClick={() => toggleRun(run.id)}
                      >
                        <td className="px-4 py-3 align-top">
                          <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-2">
                              <span
                                className={`w-2 h-2 rounded-full shrink-0 ${statusDot(displayStatus(run), run.outcome)}`}
                              />
                              <span className={`text-[11px] px-2 py-0.5 rounded w-fit ${statusBadge(displayStatus(run))}`}>
                                {displayStatus(run)}
                              </span>
                            </div>
                            <span className="text-[10px] text-gray-600 font-mono pl-4">
                              Run ID: {run.id}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 align-top text-cyan-400 font-medium">
                          {run.flow_name || <span className="text-gray-500 font-normal italic">prompt-only</span>}
                        </td>
                        <td className="px-4 py-3 align-top text-gray-500 min-w-0">
                          <span className="block truncate" title={(run.user_prompt || "").trim() || undefined}>
                            {truncateOneLine((run.user_prompt || "").trim() || "—", 120)}
                          </span>
                        </td>
                        <td className="px-4 py-3 align-top text-gray-400 tabular-nums whitespace-nowrap">
                          {duration(run.started_at, run.completed_at)}
                        </td>
                        <td className="px-4 py-3 align-top text-gray-500 tabular-nums whitespace-nowrap">
                          {formatTaskTimestamp(run.started_at || run.created_at)}
                        </td>
                        <td className="px-4 py-3 align-top text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-2">
                            {isRunActive(run) ? (
                              <button
                                type="button"
                                onClick={() => forceStopRun(run.id)}
                                className="text-xs text-red-400 hover:text-red-300"
                              >
                                Force Stop
                              </button>
                            ) : run.started_at ? (
                              <button
                                type="button"
                                onClick={() => forceStopRun(run.id)}
                                className="text-xs text-gray-600 hover:text-red-400"
                                title="Kill any lingering agent process for this run"
                              >
                                Kill
                              </button>
                            ) : null}
                            {(run.completed_at || !run.started_at) ? (
                              <button type="button" onClick={() => deleteRun(run.id)} className="text-xs text-gray-600 hover:text-red-400">
                                Delete
                              </button>
                            ) : null}
                            <span className="text-gray-600 text-[10px] ml-1">{expandedRun === run.id ? "▲" : "▼"}</span>
                          </div>
                        </td>
                      </tr>
                      {expandedRun === run.id ? (
                        <tr className="bg-gray-950/50">
                          <td colSpan={6} className="p-0 border-b border-gray-800">
                            <div className="border-t border-gray-800">
                  {/* Run prompt */}
                  {(run.user_prompt || "").trim() ? (
                    <RunPromptCollapsible text={(run.user_prompt || "").trim()} />
                  ) : null}

                  {/* Step pipeline */}
                  {(runSteps[run.id] || []).length > 0 && (
                    <div className="px-5 py-3">
                      <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-2">Steps</div>
                      <div className="flex items-center overflow-x-auto pb-1">
                        {(runSteps[run.id] || []).map((step, i) => {
                          const attempts = step.attempts || [];
                          const stepLabel = step.name === "__one_shot__" ? "one-shot" : step.name === "__summary__" ? "summary" : step.name;
                          const isCancelled = displayStatus(run) === "cancelled";
                          // Any attempt that isn't the last one caused a retry → gate failed → red.
                          // The last attempt uses its real status.
                          // If the run was cancelled, remap failed/error to skipped (grey) — not a real failure.
                          const resolveStatus = (s: string) =>
                            isCancelled && (s === "failed" || s === "error") ? "skipped" : s;
                          const attemptStatus = (att: typeof attempts[number], idx: number) =>
                            resolveStatus(idx < attempts.length - 1 ? "failed" : att.status);
                          return (
                            <div key={i} className="flex items-center">
                              {i > 0 && <div className={`w-5 h-0.5 ${stepConnectorClass(resolveStatus(step.status))}`} />}
                              {/* First attempt — the "execute" box */}
                              <div className="relative">
                                <button
                                  onClick={() => {
                                    if (!attempts[0]) return;
                                    const first = attempts[0];
                                    setLogUrl(`/api/step-runs/${first.id}/logs`);
                                    setViewingStepName(stepLabel);
                                    setSelectedAttempt(attempts.length > 1 ? { stepName: step.name, attemptId: first.id } : null);
                                    setViewingStepPrompt(first.prompt || null);
                                    setViewingStepAgentModel({ agent: first.agent || "", model: first.model || "" });
                                    // Gate failures are stored on the next attempt (the retry it caused)
                                    setViewingGateFailures(attempts[1]?.gate_failures || []);
                                  }}
                                  className={`px-3 py-1.5 rounded-md text-xs whitespace-nowrap ${stepBoxClass(attempts.length ? attemptStatus(attempts[0], 0) : step.status)} ${
                                    viewingStepName === stepLabel && (!selectedAttempt || selectedAttempt.attemptId === attempts[0]?.id)
                                      ? "border-2"
                                      : "border"
                                  } ${attempts[0] ? "cursor-pointer hover:opacity-80" : "cursor-default"}`}
                                >
                                  {stepLabel}
                                  {step.has_ifs && " \u24d8"}
                                </button>
                                {attempts[0] && attempts[0].status !== "completed" && attempts[0].status !== "running" && attempts.length === 1 && (
                                  <button
                                    onClick={(e) => { e.stopPropagation(); completeStep(attempts[0].id); }}
                                    className="absolute -bottom-2 -right-2 bg-green-700 text-white text-[8px] px-1 rounded hover:bg-green-600"
                                    title="Mark as completed"
                                  >
                                    ✓
                                  </button>
                                )}
                              </div>
                              {/* Subsequent retry attempts (oldest → newest, left → right) */}
                              {attempts.slice(1).map((att, j) => {
                                const isLast = j === attempts.length - 2;
                                return (
                                  <div key={att.id} className="flex items-center gap-1">
                                    <div className="w-3 h-0.5 bg-orange-800" />
                                    <div className="relative">
                                      <button
                                        onClick={() => {
                                          setLogUrl(`/api/step-runs/${att.id}/logs`);
                                          setViewingStepName(`${stepLabel} #${j + 2}`);
                                          setSelectedAttempt({ stepName: step.name, attemptId: att.id });
                                          setViewingStepPrompt(att.prompt || null);
                                          setViewingStepAgentModel({ agent: att.agent || "", model: att.model || "" });
                                          // Gate failures are stored on the next attempt.
                                      // Last attempt has no next → it passed (or is running) → no failures to show.
                                      const nextAtt = attempts[j + 2];
                                      setViewingGateFailures(nextAtt?.gate_failures || []);
                                        }}
                                        className={`px-1.5 py-1 rounded text-[10px] whitespace-nowrap cursor-pointer hover:opacity-80 ${
                                          selectedAttempt?.attemptId === att.id
                                            ? "border-2 " + stepBoxClass(attemptStatus(att, j + 1))
                                            : "border " + stepBoxClass(attemptStatus(att, j + 1))
                                        }`}
                                        title={`Retry #${j + 2}`}
                                      >
                                        ↻
                                      </button>
                                      {isLast && att.status !== "completed" && att.status !== "running" && (
                                        <button
                                          onClick={(e) => { e.stopPropagation(); completeStep(att.id); }}
                                          className="absolute -bottom-2 -right-2 bg-green-700 text-white text-[8px] px-1 rounded hover:bg-green-600"
                                          title="Mark as completed"
                                        >
                                          ✓
                                        </button>
                                      )}
                                    </div>
                                  </div>
                                );
                              })}
                              {/* Stop button — next to the last (rightmost/active) block */}
                              {step.status === "running" && isRunActive(run) && step.name !== "__summary__" && (
                                <button
                                  onClick={() => forceStopRun(run.id)}
                                  className="ml-1 px-1.5 py-1 rounded border border-red-700 bg-red-900/40 text-red-400 text-[10px] whitespace-nowrap cursor-pointer hover:bg-red-800/60"
                                  title="Stop run"
                                >
                                  ■
                                </button>
                              )}
                              {/* Play button to resume/re-run from this step */}
                              {run.completed_at && step.step_run && step.name !== "__summary__" && task?.task_status !== "completed" && (
                                <button
                                  onClick={() => openRetryModal(run.id, step.name)}
                                  className={`ml-1 px-1.5 py-1 rounded border text-[10px] whitespace-nowrap cursor-pointer ${
                                    step.status === "completed"
                                      ? "border-gray-700 bg-gray-800/40 text-gray-500 hover:border-green-700 hover:bg-green-900/40 hover:text-green-400"
                                      : "border-green-700 bg-green-900/40 text-green-400 hover:bg-green-800/60"
                                  }`}
                                  title={step.status === "completed" ? "Re-run from this step" : "Retry from this step"}
                                >
                                  ▶
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Log viewer - only when a step is selected */}
                  {viewingStepName && (
                    <div className="border-t border-gray-800">
                      <div className="px-5 py-2 flex items-center justify-between border-b border-gray-800/80">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="w-4 flex justify-center items-center shrink-0" aria-hidden>
                            <span className="w-2 h-2 rounded-full bg-green-500" />
                          </span>
                          <span className="text-[10px] uppercase tracking-wide text-gray-500 truncate">
                            Step:{" "}
                            <span className="text-gray-200 font-mono normal-case">{viewingStepName}</span>
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            setLogUrl(null);
                            setViewingStepName(null);
                            setViewingStepPrompt(null);
                            setViewingStepAgentModel(null);
                            setSelectedAttempt(null);
                            setViewingGateFailures([]);
                            setAgentLogExpanded(true);
                          }}
                          className="text-xs text-gray-500 hover:text-gray-300 transition shrink-0"
                        >
                          Close
                        </button>
                      </div>
                      {viewingStepAgentModel ? (
                        <div className="px-5 py-2 flex items-center gap-2 border-b border-gray-800/80">
                          <span className="w-4 flex justify-center shrink-0" aria-hidden />
                          <span className="text-[10px] uppercase tracking-wide text-gray-500 truncate">
                            MODEL:{" "}
                            <span className="text-gray-200 font-mono normal-case">
                              {viewingStepAgentModel.agent || "—"}/{viewingStepAgentModel.model || "—"}
                            </span>
                          </span>
                        </div>
                      ) : null}
                      {/* Initial prompt (when not viewing a step's injected context) */}
                      {run.prompt && !viewingStepPrompt && (
                        <CollapsiblePrompt label="Initial prompt (start.md)" text={run.prompt} />
                      )}
                      {/* Step injected context */}
                      {viewingStepPrompt && (
                        <CollapsiblePrompt label="Injected context" text={viewingStepPrompt} />
                      )}
                      {/* Gate failures that triggered this retry — hidden for cancelled runs */}
                      {viewingGateFailures.length > 0 && displayStatus(run) !== "cancelled" && (
                        <div className="border-b border-gray-800/80">
                          <details className="group [&_summary::-webkit-details-marker]:hidden px-5 py-3" open>
                            <summary className="text-[10px] uppercase tracking-wide text-orange-600 cursor-pointer select-none hover:text-orange-400 list-none inline-flex w-fit items-center gap-2 rounded-lg -ml-1 pl-1 pr-2 py-0.5">
                              <span className="w-4 flex justify-center items-center shrink-0 leading-none">
                                <span className="text-orange-700 group-open:rotate-90 transition-transform inline-block text-[9px]">▶</span>
                              </span>
                              Gate failures ({viewingGateFailures.length})
                            </summary>
                            <div className="mt-1 space-y-1.5">
                              {viewingGateFailures.map((gf, i) => (
                                <div key={i} className="bg-red-900/20 border border-red-900/50 rounded-lg p-2 text-[11px]">
                                  <code className="font-mono text-red-400 break-all">{gf.command}</code>
                                  <div className="text-gray-400 mt-0.5">{gf.message}</div>
                                  {gf.output && (
                                    <pre className="text-gray-500 mt-1 text-[10px] whitespace-pre-wrap break-all">{gf.output}</pre>
                                  )}
                                </div>
                              ))}
                            </div>
                          </details>
                        </div>
                      )}
                      <div className={agentLogExpanded ? "h-80 min-h-0" : "min-h-0"}>
                        <LogViewer
                          entries={logEntries}
                          streaming={streaming}
                          onExpandedChange={setAgentLogExpanded}
                        />
                      </div>
                    </div>
                  )}

                  {/* Run summary */}
                  {run.summary ? <RunSummarySection summary={run.summary} /> : null}
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))
                )
                }
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Run Modal */}
      {runModal && task && (
        <RunModal
          task={task}
          flows={flows}
          onClose={() => setRunModal(false)}
          onSubmit={submitRunModal}
        />
      )}

      {/* Retry Step Modal */}
      {retryModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={() => setRetryModal(null)}>
          <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-sm font-semibold mb-1">Retry step: <span className="text-cyan-400">{retryModal.stepName}</span></h2>
            <p className="text-xs text-gray-500 mb-4">Previous attempts for this step will be cleared.</p>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Additional prompt (optional)</label>
              <textarea
                value={retryPrompt}
                onChange={(e) => setRetryPrompt(e.target.value)}
                rows={3}
                placeholder="e.g. Try a different approach..."
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm resize-none"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setRetryModal(null)} className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200">
                Cancel
              </button>
              <button onClick={submitRetry} className="px-4 py-1.5 text-xs bg-green-600 text-white rounded-lg hover:bg-green-500">
                Retry
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PropField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="text-[10px] uppercase tracking-wide text-gray-600 font-medium">{label}</div>
      {children}
    </div>
  );
}

const SUMMARY_READ_MORE_THRESHOLD = 500;

function RunSummarySection({ summary }: { summary: string }) {
  const [expanded, setExpanded] = useState(false);
  const long = summary.length > SUMMARY_READ_MORE_THRESHOLD;
  const html = marked.parse(summary) as string;
  const proseClass =
    "prose prose-invert max-w-none text-gray-400 text-sm leading-relaxed " +
    "[&_h1]:text-base [&_h1]:font-bold [&_h1]:text-gray-300 [&_h1]:mt-4 [&_h1]:mb-2 " +
    "[&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-gray-300 [&_h2]:mt-3 [&_h2]:mb-1.5 " +
    "[&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-gray-300 [&_h3]:mt-2.5 [&_h3]:mb-1 " +
    "[&_p]:my-1.5 [&_p]:text-gray-400 " +
    "[&_ul]:my-1.5 [&_ul]:pl-4 [&_ul]:space-y-0.5 " +
    "[&_ol]:my-1.5 [&_ol]:pl-4 [&_ol]:space-y-0.5 " +
    "[&_li]:text-gray-400 " +
    "[&_code]:bg-gray-800 [&_code]:text-gray-300 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[11px] [&_code]:font-mono " +
    "[&_pre]:bg-gray-800 [&_pre]:border [&_pre]:border-gray-700 [&_pre]:rounded-lg [&_pre]:p-3 [&_pre]:my-2 [&_pre]:overflow-x-auto " +
    "[&_pre_code]:bg-transparent [&_pre_code]:text-gray-400 [&_pre_code]:p-0 [&_pre_code]:text-[11px] " +
    "[&_strong]:text-gray-300 [&_strong]:font-semibold " +
    "[&_a]:text-blue-400 [&_a]:underline " +
    "[&_table]:w-full [&_table]:my-2 [&_table]:text-[11px] [&_table]:border-collapse " +
    "[&_th]:text-left [&_th]:text-gray-400 [&_th]:font-semibold [&_th]:border-b [&_th]:border-gray-700 [&_th]:px-2 [&_th]:py-1.5 " +
    "[&_td]:text-gray-400 [&_td]:border-b [&_td]:border-gray-800 [&_td]:px-2 [&_td]:py-1.5 [&_td]:align-top " +
    "[&_tr:last-child_td]:border-b-0";

  return (
    <div className="px-5 py-3">
      <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-1">Summary</div>
      <div className="relative">
        <div
          className={`${proseClass}${!expanded && long ? " max-h-48 overflow-hidden" : ""}`}
          dangerouslySetInnerHTML={{ __html: html }}
        />
        {!expanded && long ? (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-gray-950 via-gray-950/70 to-transparent"
            aria-hidden
          />
        ) : null}
      </div>
      {long ? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((v) => !v);
          }}
          className="relative z-10 text-xs text-blue-400 hover:text-blue-300 mt-2"
        >
          {expanded ? "Read less" : "Read more"}
        </button>
      ) : null}
    </div>
  );
}

function RunPromptCollapsible({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 400 || text.split("\n").length > 6;
  return (
    <div className="px-5 py-3 border-b border-gray-800">
      <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-1">Prompt</div>
      <div
        className={`text-xs text-gray-400 whitespace-pre-wrap font-mono bg-gray-900/50 border border-gray-800 rounded-lg p-3 ${
          !open && long ? "max-h-32 overflow-hidden" : ""
        }`}
      >
        {text}
      </div>
      {long ? (
        <button type="button" onClick={() => setOpen((o) => !o)} className="text-xs text-blue-400 hover:text-blue-300 mt-1.5">
          {open ? "Show less" : "Show more"}
        </button>
      ) : null}
    </div>
  );
}

function CollapsiblePrompt({ label, text }: { label: string; text: string }) {
  return (
    <div className="border-b border-gray-800/80">
      <details className="group [&_summary::-webkit-details-marker]:hidden px-5 py-3">
        <summary className="text-[10px] uppercase tracking-wide text-gray-600 cursor-pointer select-none list-none inline-flex w-fit max-w-full items-center gap-2 rounded-lg -ml-1 pl-1 pr-2 py-0.5 hover:bg-gray-800/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50">
          <span className="w-4 flex justify-center items-center shrink-0 leading-none" aria-hidden>
            <span className="text-gray-700 group-open:rotate-90 transition-transform inline-block text-[9px]">
              ▶
            </span>
          </span>
          <span>{label}</span>
        </summary>
        <pre className="mt-2 text-gray-500 text-[11px] whitespace-pre-wrap font-mono bg-gray-900 border border-gray-800 rounded-lg p-3 max-h-64 overflow-y-auto">
          {text}
        </pre>
      </details>
    </div>
  );
}
