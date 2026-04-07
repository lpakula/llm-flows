import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { useLogStream } from "@/hooks/useEventSource";
import { useApp } from "@/App";
import { LogViewer } from "@/components/LogViewer";
import type { Task, TaskRun, StepRunInfo, Flow, GateFailure } from "@/api/types";
import { statusBadge, displayStatus, duration, stepBoxClass, stepConnectorClass } from "@/lib/format";
import { marked } from "marked";

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

  // Run modal state
  const [runModal, setRunModal] = useState(false);
  const [runModalFlow, setRunModalFlow] = useState<string>("");
  const [runModalPrompt, setRunModalPrompt] = useState("");
  const [runModalOneShot, setRunModalOneShot] = useState(false);
  const [flows, setFlows] = useState<Flow[]>([]);

  // Retry modal
  const [retryModal, setRetryModal] = useState<{ runId: string; stepName: string } | null>(null);
  const [retryPrompt, setRetryPrompt] = useState("");

  // Selected attempt for viewing logs
  const [selectedAttempt, setSelectedAttempt] = useState<{ stepName: string; attemptId: string } | null>(null);
  const [viewingStepPrompt, setViewingStepPrompt] = useState<string | null>(null);
  const [viewingGateFailures, setViewingGateFailures] = useState<GateFailure[]>([]);

  // Description editing
  const [editingDesc, setEditingDesc] = useState(false);
  const [editDescText, setEditDescText] = useState("");

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
          const activeRun = r.find((run) => isRunActive(run));
          if (activeRun) {
            setExpandedRun(activeRun.id);
            const data = await api.getRunSteps(activeRun.id);
            setRunSteps((prev) => ({ ...prev, [activeRun.id]: data.steps }));
            const steps = data.steps;
            const activeStep = steps.find((s) => s.step_run && s.status === "running");
            if (activeStep?.step_run) {
              setLogUrl(`/api/step-runs/${activeStep.step_run.id}/logs`);
              setViewingStepName(activeStep.name);
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
      setViewingGateFailures([]);
    } else {
      setExpandedRun(runId);
      setLogUrl(null);
      setViewingStepName(null);
      setSelectedAttempt(null);
      setViewingStepPrompt(null);
      setViewingGateFailures([]);
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
    setSelectedAttempt(null);
    setViewingGateFailures([]);
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
    setRunModalPrompt("");
    setRunModalOneShot(false);
    const fl = await api.listFlows(task.project_id);
    setFlows(fl);
    setRunModalFlow(task.default_flow_name || "");
    setRunModal(true);
  };

  const submitRunModal = async () => {
    if (!task) return;
    let prompt = runModalPrompt;
    if (runs.length === 0 && runModalPrompt.trim()) {
      const desc = (task.description || "").trim();
      prompt = desc ? desc + "\n\n" + runModalPrompt.trim() : runModalPrompt.trim();
    }
    await api.startTask(task.id, {
      flow: runModalFlow || null,
      user_prompt: prompt,
      one_shot: runModalOneShot,
    });
    setRunModal(false);
    setRuns(await api.listTaskRuns(task.id));
  };

  const saveDescription = async () => {
    if (!task) return;
    const updated = await api.updateTask(task.id, { description: editDescText });
    setTask(updated);
    setEditingDesc(false);
  };

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => task ? navigate(`/project/${task.project_id}`) : navigate("/")}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            &larr; Back
          </button>
          <h2 className="text-base font-medium">{task?.name || "Loading..."}</h2>
          <span className="text-[10px] uppercase text-gray-500 font-medium">{task?.type}</span>
        </div>
        <button
          onClick={openRunModal}
          className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition"
        >
          Start Run
        </button>
      </header>

      {/* Description */}
      {task && (
        <div className="px-6 py-3 border-b border-gray-800">
          {!editingDesc ? (
            <div className="flex items-start gap-2">
              <p className="text-sm text-gray-400 flex-1 whitespace-pre-wrap">
                {task.description || <span className="italic text-gray-600">No description</span>}
              </p>
              <button
                onClick={() => { setEditDescText(task.description || ""); setEditingDesc(true); }}
                className="text-xs text-gray-600 hover:text-gray-400 flex-shrink-0"
              >
                Edit
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <textarea
                value={editDescText}
                onChange={(e) => setEditDescText(e.target.value)}
                rows={4}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                autoFocus
              />
              <div className="flex gap-2">
                <button onClick={saveDescription} className="text-xs text-blue-400 hover:text-blue-300">Save</button>
                <button onClick={() => setEditingDesc(false)} className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Runs */}
      <div className="p-6">
        <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
          Runs ({runs.length})
        </h3>
        <div className="space-y-2">
          {runs.map((run) => (
            <div key={run.id} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div
                className="px-5 py-3 flex items-center justify-between cursor-pointer hover:bg-gray-800/50"
                onClick={() => toggleRun(run.id)}
              >
                <div className="flex items-center gap-3">
                  <span className={`text-xs px-2 py-0.5 rounded ${statusBadge(displayStatus(run))}`}>
                    {displayStatus(run)}
                  </span>
                  {run.flow_name && <span className="text-xs text-cyan-400">{run.flow_name}</span>}
                  {!run.flow_name && <span className="text-xs text-gray-500 italic">prompt-only</span>}
                  <span className="text-xs text-gray-500">{duration(run.started_at, run.completed_at)}</span>
                </div>
                <div className="flex items-center gap-2">
                  {isRunActive(run) && (
                    <button
                      onClick={(e) => { e.stopPropagation(); forceStopRun(run.id); }}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Force Stop
                    </button>
                  )}
                  {run.completed_at && (
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteRun(run.id); }}
                      className="text-xs text-gray-600 hover:text-red-400"
                    >
                      Delete
                    </button>
                  )}
                  <span className="text-xs text-gray-600">{expandedRun === run.id ? "▲" : "▼"}</span>
                </div>
              </div>

              {expandedRun === run.id && (
                <div className="border-t border-gray-800">
                  {/* Run summary */}
                  {run.summary && (
                    <div className="px-5 py-3">
                      <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-1">Summary</div>
                      <div
                        className="prose prose-invert max-w-none text-gray-300 text-xs leading-relaxed
                          [&_h1]:text-base [&_h1]:font-bold [&_h1]:text-white [&_h1]:mt-4 [&_h1]:mb-2
                          [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-gray-100 [&_h2]:mt-3 [&_h2]:mb-1.5
                          [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-gray-200 [&_h3]:mt-2.5 [&_h3]:mb-1
                          [&_p]:my-1.5 [&_p]:text-gray-300
                          [&_ul]:my-1.5 [&_ul]:pl-4 [&_ul]:space-y-0.5
                          [&_ol]:my-1.5 [&_ol]:pl-4 [&_ol]:space-y-0.5
                          [&_li]:text-gray-300
                          [&_code]:bg-gray-800 [&_code]:text-cyan-300 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[11px] [&_code]:font-mono
                          [&_pre]:bg-gray-800 [&_pre]:border [&_pre]:border-gray-700 [&_pre]:rounded-lg [&_pre]:p-3 [&_pre]:my-2 [&_pre]:overflow-x-auto
                          [&_pre_code]:bg-transparent [&_pre_code]:text-green-300 [&_pre_code]:p-0 [&_pre_code]:text-[11px]
                          [&_strong]:text-gray-100 [&_strong]:font-semibold
                          [&_a]:text-blue-400 [&_a]:underline
                          [&_table]:w-full [&_table]:my-2 [&_table]:text-[11px] [&_table]:border-collapse
                          [&_th]:text-left [&_th]:text-gray-300 [&_th]:font-semibold [&_th]:border-b [&_th]:border-gray-700 [&_th]:px-2 [&_th]:py-1.5
                          [&_td]:text-gray-400 [&_td]:border-b [&_td]:border-gray-800 [&_td]:px-2 [&_td]:py-1.5 [&_td]:align-top
                          [&_tr:last-child_td]:border-b-0"
                        dangerouslySetInnerHTML={{ __html: marked.parse(run.summary) as string }}
                      />
                    </div>
                  )}

                  {/* Step pipeline */}
                  {(runSteps[run.id] || []).length > 0 && (
                    <div className="px-5 py-3">
                      <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-2">Steps</div>
                      <div className="flex items-center gap-1 overflow-x-auto pb-1">
                        {(runSteps[run.id] || []).map((step, i) => {
                          const attempts = step.attempts || [];
                          const stepLabel = step.name === "__one_shot__" ? "one-shot" : step.name === "__summary__" ? "summary" : step.name;
                          return (
                            <div key={i} className="flex items-center gap-1">
                              {i > 0 && <div className={`w-4 h-0.5 ${stepConnectorClass(step.status)}`} />}
                              <div className="relative">
                                <button
                                  onClick={() => {
                                    if (!step.step_run) return;
                                    viewStepLogs(step);
                                    setSelectedAttempt(null);
                                  }}
                                  className={`px-2 py-1 rounded text-[11px] whitespace-nowrap ${stepBoxClass(step.status)} ${
                                    viewingStepName === stepLabel && !selectedAttempt
                                      ? "border-2"
                                      : "border"
                                  } ${step.step_run ? "cursor-pointer hover:opacity-80" : "cursor-default"}`}
                                >
                                  {stepLabel}
                                  {step.has_ifs && " \u24d8"}
                                </button>
                                {step.step_run && step.status !== "completed" && step.status !== "running" && (
                                  <button
                                    onClick={(e) => { e.stopPropagation(); completeStep(step.step_run!.id); }}
                                    className="absolute -bottom-2 -right-2 bg-green-700 text-white text-[8px] px-1 rounded hover:bg-green-600"
                                    title="Mark as completed"
                                  >
                                    ✓
                                  </button>
                                )}
                              </div>
                              {/* Stop button next to running step (not on summary) */}
                              {step.status === "running" && isRunActive(run) && step.name !== "__summary__" && (
                                <button
                                  onClick={() => forceStopRun(run.id)}
                                  className="ml-1 px-1.5 py-1 rounded border border-red-700 bg-red-900/40 text-red-400 text-[10px] whitespace-nowrap cursor-pointer hover:bg-red-800/60"
                                  title="Stop run"
                                >
                                  ■
                                </button>
                              )}
                              {/* Play button to retry/resume from this step */}
                              {run.completed_at && step.status !== "completed" && step.step_run && (
                                <button
                                  onClick={() => openRetryModal(run.id, step.name)}
                                  className="ml-1 px-1.5 py-1 rounded border border-green-700 bg-green-900/40 text-green-400 text-[10px] whitespace-nowrap cursor-pointer hover:bg-green-800/60"
                                  title="Retry from this step"
                                >
                                  ▶
                                </button>
                              )}
                              {/* Gate retry blocks */}
                              {attempts.length > 1 && attempts.slice(0, -1).map((att, j) => (
                                <div key={att.id} className="flex items-center gap-1">
                                  <div className="w-3 h-0.5 bg-orange-800" />
                                  <button
                                    onClick={() => {
                                      setLogUrl(`/api/step-runs/${att.id}/logs`);
                                      setViewingStepName(`${stepLabel} #${j + 1}`);
                                      setSelectedAttempt({ stepName: step.name, attemptId: att.id });
                                      setViewingStepPrompt(att.prompt || null);
                                      setViewingGateFailures(att.gate_failures || []);
                                    }}
                                    className={`px-1.5 py-1 rounded text-[10px] whitespace-nowrap cursor-pointer hover:opacity-80 ${
                                      selectedAttempt?.attemptId === att.id
                                        ? "border-2 bg-orange-900/50 border-orange-500 text-orange-300"
                                        : "border bg-orange-900/30 border-orange-800 text-orange-500"
                                    }`}
                                    title={`Retry #${j + 1}`}
                                  >
                                    ↻
                                  </button>
                                </div>
                              ))}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Log viewer - only when a step is selected */}
                  {viewingStepName && (
                    <div className="border-t border-gray-800">
                      <div className="px-5 py-1.5 flex items-center justify-end">
                        <button
                          onClick={() => { setLogUrl(null); setViewingStepName(null); setViewingStepPrompt(null); setSelectedAttempt(null); setViewingGateFailures([]); }}
                          className="text-xs text-gray-500 hover:text-gray-300 transition"
                        >
                          Close
                        </button>
                      </div>
                      {/* Initial prompt (when not viewing a step's injected context) */}
                      {run.prompt && !viewingStepPrompt && (
                        <CollapsiblePrompt label="Initial prompt (start.md)" text={run.prompt} />
                      )}
                      {/* Step injected context */}
                      {viewingStepPrompt && (
                        <CollapsiblePrompt label="Injected context" text={viewingStepPrompt} />
                      )}
                      {/* Gate failures that triggered this retry */}
                      {viewingGateFailures.length > 0 && (
                        <div className="px-5 mb-2">
                          <details className="group" open>
                            <summary className="text-[10px] uppercase tracking-wide text-orange-600 cursor-pointer select-none hover:text-orange-400 list-none flex items-center gap-1">
                              <span className="text-orange-700 group-open:rotate-90 transition-transform inline-block">▶</span>
                              Gate failures ({viewingGateFailures.length})
                            </summary>
                            <div className="mt-1 space-y-1.5">
                              {viewingGateFailures.map((gf, i) => (
                                <div key={i} className="bg-red-900/20 border border-red-900/50 rounded-lg p-2 text-[11px]">
                                  <div className="font-mono text-red-400">{gf.command}</div>
                                  <div className="text-gray-400 mt-0.5">{gf.message}</div>
                                  {gf.output && (
                                    <pre className="text-gray-500 mt-1 text-[10px] whitespace-pre-wrap">{gf.output}</pre>
                                  )}
                                </div>
                              ))}
                            </div>
                          </details>
                        </div>
                      )}
                      <div className="h-80">
                        <LogViewer entries={logEntries} streaming={streaming} />
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Run Modal */}
      {runModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={() => setRunModal(false)}>
          <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-sm font-semibold mb-4">Start Run</h2>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500 block mb-1">Flow</label>
                <select
                  value={runModalFlow}
                  onChange={(e) => setRunModalFlow(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">No flow (prompt only)</option>
                  {flows.map((f) => (
                    <option key={f.id} value={f.name}>
                      {f.name} ({f.step_count} steps)
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">Additional prompt (optional)</label>
                <textarea
                  value={runModalPrompt}
                  onChange={(e) => setRunModalPrompt(e.target.value)}
                  rows={3}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm resize-none"
                />
              </div>
              {runModalFlow && (
                <label className="flex items-center gap-2 text-sm text-gray-400">
                  <input
                    type="checkbox"
                    checked={runModalOneShot}
                    onChange={(e) => setRunModalOneShot(e.target.checked)}
                    className="rounded"
                  />
                  One-shot mode (skip flow steps, use prompt only)
                </label>
              )}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setRunModal(false)} className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200">
                Cancel
              </button>
              <button
                onClick={submitRunModal}
                className="px-4 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-500"
              >
                Start
              </button>
            </div>
          </div>
        </div>
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

function CollapsiblePrompt({ label, text }: { label: string; text: string }) {
  return (
    <div className="px-5 mb-2">
      <details className="group">
        <summary className="text-[10px] uppercase tracking-wide text-gray-600 cursor-pointer select-none hover:text-gray-400 list-none flex items-center gap-1">
          <span className="text-gray-700 group-open:rotate-90 transition-transform inline-block">▶</span>
          {label}
        </summary>
        <pre className="mt-1 text-gray-500 text-[11px] whitespace-pre-wrap font-mono bg-gray-900 border border-gray-800 rounded-lg p-3 max-h-64 overflow-y-auto">
          {text}
        </pre>
      </details>
    </div>
  );
}
