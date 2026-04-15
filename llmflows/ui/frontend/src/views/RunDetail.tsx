import { useState, useEffect, useCallback, Fragment } from "react";
import type { ReactNode } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { useLogStream } from "@/hooks/useEventSource";
import { LogViewer } from "@/components/LogViewer";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { FlowRun, StepRunInfo, GateFailure } from "@/api/types";
import { statusBadge, displayStatus, duration, formatSeconds, stepBoxClass, stepConnectorClass, statusDot } from "@/lib/format";
import { UserCheck, Check } from "lucide-react";
import { ImageLightbox } from "@/components/ImageLightbox";
import { AttachmentsGrid } from "@/components/AttachmentsGrid";
import { marked } from "marked";

function formatTimestamp(iso: string | undefined | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").toLocaleString();
  } catch {
    return iso;
  }
}

export function RunDetailView() {
  const { projectId, runId } = useParams<{ projectId: string; runId: string }>();
  const navigate = useNavigate();

  const [run, setRun] = useState<FlowRun | null>(null);
  const [steps, setSteps] = useState<StepRunInfo[]>([]);
  const [logUrl, setLogUrl] = useState<string | null>(null);
  const [viewingStepName, setViewingStepName] = useState<string | null>(null);

  const [retryModal, setRetryModal] = useState<{ stepName: string } | null>(null);

  const [respondingStep, setRespondingStep] = useState<{ stepRunId: string; stepType: string } | null>(null);
  const [respondText, setRespondText] = useState("");

  const [selectedAttempt, setSelectedAttempt] = useState<{ stepName: string; attemptId: string } | null>(null);
  const [viewingStepPrompt, setViewingStepPrompt] = useState<string | null>(null);
  const [viewingStepAgentModel, setViewingStepAgentModel] = useState<{ agent: string; model: string } | null>(null);
  const [viewingStepDuration, setViewingStepDuration] = useState<number | null>(null);
  const [viewingGateFailures, setViewingGateFailures] = useState<GateFailure[]>([]);
  const [agentLogExpanded, setAgentLogExpanded] = useState(true);

  const { entries: logEntries, streaming } = useLogStream(logUrl, null);

  const isActive = run ? !!run.started_at && !run.completed_at : false;

  const loadRun = useCallback(async () => {
    if (!runId || !projectId) return;
    try {
      const allRuns = await api.listFlowRuns(projectId);
      const found = allRuns.find((r) => r.id === runId);
      if (found) {
        setRun(found);
        const data = await api.getRunSteps(runId);
        setSteps(data.steps);
      }
    } catch (e) {
      console.error("Run load error:", e);
    }
  }, [runId, projectId]);

  useEffect(() => {
    const init = async () => {
      if (!runId || !projectId) return;
      const allRuns = await api.listFlowRuns(projectId);
      const found = allRuns.find((r) => r.id === runId);
      if (!found) return;
      setRun(found);

      const data = await api.getRunSteps(runId);
      setSteps(data.steps);

      const activeStep = data.steps.find(
        (s) => s.step_run && (s.status === "running" || s.status === "awaiting_user"),
      );
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
        setViewingStepDuration(activeStep.step_run.duration_seconds ?? null);
      }
    };
    init();
  }, [runId, projectId]);

  useInterval(loadRun, 5000);

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
    setViewingStepDuration(step.step_run.duration_seconds ?? null);
    setViewingGateFailures(step.step_run.gate_failures || []);
  };

  const forceStopRun = async () => {
    if (!run) return;
    if (!confirm("Force stop this run? The agent process will be killed.")) return;
    await api.stopRun(run.id);
    setLogUrl(null);
    loadRun();
  };

  const respondToStep = async (stepRunId: string, response: string) => {
    await api.respondToStep(stepRunId, response);
    setRespondingStep(null);
    setRespondText("");
    loadRun();
  };

  const submitRetry = async (stepName: string) => {
    if (!run) return;
    setLogUrl(null);
    setViewingStepName(null);
    setViewingStepPrompt(null);
    setViewingStepAgentModel(null);
    setViewingStepDuration(null);
    setSelectedAttempt(null);
    setViewingGateFailures([]);
    setAgentLogExpanded(true);
    await api.retryStep(run.id, stepName);
    loadRun();
  };

  const deleteRun = async () => {
    if (!run) return;
    if (!confirm("Delete this run?")) return;
    await api.deleteRun(run.id);
    navigate(`/project/${projectId}`);
  };

  const label = run ? displayStatus(run) : "";

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        <button
          onClick={() => navigate(`/project/${projectId}`)}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          &larr; Back to Board
        </button>
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2 gap-y-1">
            <h1 className="text-xl font-semibold text-white tracking-tight">
              {run?.flow_name || "Run"}
            </h1>
            {run && (
              <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${statusBadge(label)}`}>
                {label}
              </span>
            )}
          </div>

          {run && (
            <div className="mt-4 mb-4 flex flex-wrap gap-x-6 gap-y-3">
              <PropField label="Run ID">
                <span className="text-sm font-mono text-gray-400">{run.id}</span>
              </PropField>
              <PropField label="Flow">
                <span className="text-sm text-cyan-400">{run.flow_name || "—"}</span>
              </PropField>
              <PropField label="Started">
                <span className="text-sm text-gray-400 tabular-nums">{formatTimestamp(run.started_at)}</span>
              </PropField>
              {run.completed_at && (
                <PropField label="Completed">
                  <span className="text-sm text-gray-400 tabular-nums">{formatTimestamp(run.completed_at)}</span>
                </PropField>
              )}
              {run.duration_seconds != null && (
                <PropField label="Duration">
                  <span className="text-sm text-gray-400 tabular-nums">{formatSeconds(run.duration_seconds)}</span>
                </PropField>
              )}
            </div>
          )}

          {/* Actions */}
          {run && (
            <div className="flex items-center gap-3">
              {isActive && (
                <button
                  onClick={forceStopRun}
                  className="text-xs text-red-400 hover:text-red-300 transition"
                >
                  Force Stop
                </button>
              )}
              {(run.completed_at || !run.started_at) && (
                <button onClick={deleteRun} className="text-xs text-gray-600 hover:text-red-400 transition">
                  Delete Run
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Steps & log */}
      <div className="p-6">
        {/* Step pipeline */}
        {steps.length > 0 && (
          <div className="mb-4">
            <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-2">Steps</div>
            <div className="flex items-center overflow-x-auto pb-1">
              {steps.map((step, i) => {
                const attempts = step.attempts || [];
                const stepLabel = step.name === "__one_shot__" ? "one-shot" : step.name === "__summary__" ? "summary" : step.name;
                const isCancelled = run ? displayStatus(run) === "cancelled" : false;
                const resolveStatus = (s: string) =>
                  isCancelled && (s === "failed" || s === "error") ? "skipped" : s;
                const attemptStatus = (att: typeof attempts[number], idx: number) =>
                  resolveStatus(idx < attempts.length - 1 ? "failed" : att.status);
                return (
                  <div key={i} className="flex items-center">
                    {i > 0 && <div className={`w-5 h-0.5 ${stepConnectorClass(resolveStatus(step.status))}`} />}
                    {run?.completed_at && run.outcome !== "completed" && step.step_run && step.name !== "__summary__" && (
                      <button
                        onClick={() => setRetryModal({ stepName: step.name })}
                        className={`mr-1 px-1.5 py-1 rounded border text-[10px] whitespace-nowrap cursor-pointer ${
                          step.status === "completed"
                            ? "border-gray-700 bg-gray-800/40 text-gray-500 hover:border-green-700 hover:bg-green-900/40 hover:text-green-400"
                            : "border-green-700 bg-green-900/40 text-green-400 hover:bg-green-800/60"
                        }`}
                        title={step.status === "completed" ? "Re-run from this step" : "Retry from this step"}
                      >
                        ▶
                      </button>
                    )}
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
                          setViewingStepDuration(first.duration_seconds ?? null);
                          setViewingGateFailures(attempts[1]?.gate_failures || []);
                        }}
                        className={`px-3 py-1.5 rounded-md text-xs whitespace-nowrap ${stepBoxClass(attempts.length ? attemptStatus(attempts[0], 0) : step.status)} ${
                          viewingStepName === stepLabel && (!selectedAttempt || selectedAttempt.attemptId === attempts[0]?.id)
                            ? "border-2"
                            : "border"
                        } ${attempts[0] ? "cursor-pointer hover:opacity-80" : "cursor-default"}`}
                      >
                        {step.step_type === "manual" && <UserCheck size={10} className="inline mr-1 -mt-px opacity-60" />}
                        {stepLabel}
                        {step.has_ifs && <span className="ml-1 text-purple-400 font-medium">if</span>}
                      </button>
                    </div>
                    {attempts.slice(1).map((att, j) => (
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
                              setViewingStepDuration(att.duration_seconds ?? null);
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
                        </div>
                      </div>
                    ))}
                    {step.status === "running" && isActive && step.name !== "__summary__" && (
                      <button
                        onClick={forceStopRun}
                        className="ml-1 px-1.5 py-1 rounded border border-red-700 bg-red-900/40 text-red-400 text-[10px] whitespace-nowrap cursor-pointer hover:bg-red-800/60"
                        title="Stop run"
                      >
                        ■
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Awaiting user inline respond */}
        {(() => {
          const awaitingStep = steps.find(
            (s) => s.status === "awaiting_user" && s.step_run,
          );
          if (!awaitingStep?.step_run) return null;
          const stepLabel = awaitingStep.name === "__summary__" ? "summary" : awaitingStep.name;
          return (
            <div className="mb-4 rounded-xl border border-amber-900/40 bg-amber-950/10 px-5 py-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                <span className="text-xs font-medium text-amber-400">
                  Awaiting input: {stepLabel}
                </span>
              </div>
              {awaitingStep.step_run!.user_message && (
                <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mb-3 max-h-64 overflow-y-auto">
                  <MarkdownContent text={awaitingStep.step_run!.user_message} className="text-sm text-gray-300" />
                </div>
              )}
              <div className="space-y-2">
                <textarea
                  value={respondingStep?.stepRunId === awaitingStep.step_run!.id ? respondText : ""}
                  onChange={(e) => {
                    setRespondingStep({ stepRunId: awaitingStep.step_run!.id, stepType: "manual" });
                    setRespondText(e.target.value);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && respondText.trim()) {
                      e.preventDefault();
                      respondToStep(awaitingStep.step_run!.id, respondText);
                    }
                  }}
                  placeholder="Type your response..."
                  rows={1}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-600 focus:border-gray-600 resize-none overflow-hidden"
                  onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; }}
                />
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => respondToStep(awaitingStep.step_run!.id, respondText)}
                    disabled={!respondText.trim()}
                    className="inline-flex items-center gap-1 px-2 py-1 text-green-500 hover:text-green-400 disabled:opacity-40 text-xs font-medium transition"
                  >
                    <Check size={12} />
                    Submit
                  </button>
                  <span className="text-[10px] text-gray-700">Enter to submit, Shift+Enter for new line</span>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Log viewer */}
        {viewingStepName && run && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden mb-4">
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
                  setViewingStepDuration(null);
                  setSelectedAttempt(null);
                  setViewingGateFailures([]);
                  setAgentLogExpanded(true);
                }}
                className="text-xs text-gray-500 hover:text-gray-300 transition shrink-0"
              >
                Close
              </button>
            </div>
            {viewingStepAgentModel && (
              <div className="px-5 py-2 flex items-center gap-2 border-b border-gray-800/80">
                <span className="w-4 flex justify-center shrink-0" aria-hidden />
                <span className="text-[10px] uppercase tracking-wide text-gray-500 truncate">
                  MODEL:{" "}
                  <span className="text-gray-200 font-mono normal-case">
                    {viewingStepAgentModel.agent || "—"}/{viewingStepAgentModel.model || "—"}
                  </span>
                </span>
              </div>
            )}
            {viewingStepDuration != null && (
              <div className="px-5 py-2 flex items-center gap-2 border-b border-gray-800/80">
                <span className="w-4 flex justify-center shrink-0" aria-hidden />
                <span className="text-[10px] uppercase tracking-wide text-gray-500 truncate">
                  DURATION:{" "}
                  <span className="text-gray-200 font-mono normal-case">
                    {formatSeconds(viewingStepDuration)}
                  </span>
                </span>
              </div>
            )}
            {run.prompt && !viewingStepPrompt && (
              <CollapsiblePrompt label="Initial prompt (start.md)" text={run.prompt} />
            )}
            {viewingStepPrompt && (
              <CollapsiblePrompt label="Injected context" text={viewingStepPrompt} />
            )}
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
        {run?.summary && (
          <RunSummarySection summary={run.summary} attachments={run.attachments || []} />
        )}
      </div>

      {retryModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={() => setRetryModal(null)}>
          <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-sm font-semibold mb-1">Retry step: <span className="text-cyan-400">{retryModal.stepName}</span></h2>
            <p className="text-xs text-gray-500 mb-4">Previous attempts for this and subsequent steps will be cleared.</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setRetryModal(null)} className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200">
                Cancel
              </button>
              <button
                onClick={() => { submitRetry(retryModal.stepName); setRetryModal(null); }}
                className="px-4 py-1.5 text-xs bg-green-600 text-white rounded-lg hover:bg-green-500"
              >
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

function RunSummarySection({ summary, attachments }: { summary: string; attachments: { name: string; url: string }[] }) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
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
    "[&_img]:max-w-[180px] [&_img]:max-h-[120px] [&_img]:object-contain [&_img]:rounded-md [&_img]:border [&_img]:border-gray-700 [&_img]:cursor-zoom-in [&_img]:inline-block [&_img]:mr-2 [&_img]:my-1 " +
    "[&_table]:w-full [&_table]:my-2 [&_table]:text-[11px] [&_table]:border-collapse " +
    "[&_th]:text-left [&_th]:text-gray-400 [&_th]:font-semibold [&_th]:border-b [&_th]:border-gray-700 [&_th]:px-2 [&_th]:py-1.5 " +
    "[&_td]:text-gray-400 [&_td]:border-b [&_td]:border-gray-800 [&_td]:px-2 [&_td]:py-1.5 [&_td]:align-top " +
    "[&_tr:last-child_td]:border-b-0";

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.tagName === "IMG") {
      e.preventDefault();
      setLightboxSrc((target as HTMLImageElement).src);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-3">
      <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-1">Summary</div>
      <div className={proseClass} onClick={handleClick}>
        <div dangerouslySetInnerHTML={{ __html: html }} />
        <AttachmentsGrid files={attachments} />
      </div>
      {lightboxSrc && <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />}
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
