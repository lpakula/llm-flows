import { useState } from "react";
import type { Task, Flow } from "@/api/types";
import { MarkdownContent } from "@/components/MarkdownContent";

export function RunModal({
  task,
  flows,
  onClose,
  onSubmit,
}: {
  task: Task;
  flows: Flow[];
  onClose: () => void;
  onSubmit: (taskId: string, opts: { flow: string; prompt: string; one_shot: boolean }) => Promise<void>;
}) {
  const [flow, setFlow] = useState(task.default_flow_name || "");
  const [prompt, setPrompt] = useState("");
  const [oneShot, setOneShot] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const hasRuns = task.run_count > 0;

  const selectedFlow = flows.find((f) => f.name === flow);
  const hasHumanSteps = selectedFlow?.steps.some(
    (s) => s.step_type === "manual" || s.step_type === "prompt",
  ) ?? false;

  const submit = async () => {
    setSubmitting(true);
    try {
      await onSubmit(task.id, { flow, prompt: prompt.trim(), one_shot: oneShot });
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-base font-semibold mb-1">New Run</h2>
        <p className="text-xs text-gray-500 mb-5">{task.name}</p>

        <div className="space-y-5">
          {/* Flow */}
          <div>
            <label className="text-sm text-gray-400 block mb-2">Flow</label>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setFlow("")}
                className={`px-3 py-1 rounded-lg text-sm font-mono transition ${
                  flow === ""
                    ? "border-2 border-blue-500 text-blue-300 bg-blue-500/10"
                    : "border border-gray-600 text-gray-400 hover:border-gray-400 hover:text-gray-200"
                }`}
              >
                none
              </button>
              {flows.map((f) => (
                <button
                  key={f.id}
                  onClick={() => setFlow(f.name)}
                  className={`px-3 py-1 rounded-lg text-sm font-mono transition ${
                    flow === f.name
                      ? "border-2 border-blue-500 text-blue-300 bg-blue-500/10"
                      : "border border-gray-600 text-gray-400 hover:border-gray-400 hover:text-gray-200"
                  }`}
                >
                  {f.name}
                </button>
              ))}
            </div>
          </div>

          {/* Prompt */}
          <div>
            <label className="text-sm text-gray-400 block mb-2">Prompt</label>
            {!hasRuns && (
              <>
                <p className="text-[10px] uppercase tracking-widest text-gray-600 mb-2">
                  Task description (included automatically)
                </p>
                <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 min-h-[36px] max-h-48 overflow-y-auto mb-3">
                  {(task.description || "").trim() ? (
                    <MarkdownContent text={(task.description || "").trim()} />
                  ) : (
                    <span className="text-sm text-gray-600 italic">No description</span>
                  )}
                </div>
              </>
            )}
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              autoFocus
              placeholder={hasRuns ? "What should the agent do?" : "Additional instructions (optional)"}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono text-gray-200 placeholder:text-gray-600 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/50"
            />
          </div>

          {/* One-shot */}
          <div>
            <label className={`flex items-center gap-2 text-sm select-none ${hasHumanSteps ? "cursor-not-allowed text-gray-600" : "cursor-pointer text-gray-400"}`}>
              <input
                type="checkbox"
                checked={oneShot && !hasHumanSteps}
                onChange={(e) => setOneShot(e.target.checked)}
                disabled={hasHumanSteps}
                className="rounded"
              />
              One-shot
            </label>
            <p className="text-xs text-gray-600 mt-1 ml-5">
              {hasHumanSteps
                ? "Not available — this flow contains manual or prompt steps that require user interaction."
                : <>All flow steps and their gates are combined into a single prompt and handed to the agent at once. Gates are included as guidance but not enforced — no retries, no step-by-step validation. Uses the <span className="text-gray-400 font-mono">max</span> alias (highest-capability model).</>
              }
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-3 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting || (hasRuns && !prompt.trim())}
            className="px-5 py-2 text-sm bg-blue-600 text-white rounded-xl hover:bg-blue-500 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitting ? "Starting…" : "Run"}
          </button>
        </div>
      </div>
    </div>
  );
}
