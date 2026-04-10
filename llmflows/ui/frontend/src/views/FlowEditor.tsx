import { useState, useEffect, useCallback, useRef, type ReactNode } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useApp } from "@/App";
import type { Flow, FlowStep, Gate, AgentAlias } from "@/api/types";

const VARIABLES = ["{{run.id}}", "{{task.id}}", "{{flow.name}}", "{{artifacts_output_dir}}", "{{steps.<name>.user_response}}"];

function GateEditor({
  label,
  subtitle,
  addLabel,
  items,
  onChange,
}: {
  label: string;
  subtitle: string;
  addLabel: string;
  items: Gate[];
  onChange: (items: Gate[]) => void;
}) {
  const add = () => onChange([...items, { command: "", message: "" }]);
  const remove = (i: number) => onChange(items.filter((_, idx) => idx !== i));
  const update = (i: number, field: keyof Gate, value: string) => {
    const next = [...items];
    next[i] = { ...next[i], [field]: value };
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 font-medium">{label}</span>
          <span className="text-xs text-gray-600">{subtitle}</span>
        </div>
        <button onClick={add} className="text-xs text-blue-400 hover:text-blue-300 mt-1">
          {addLabel}
        </button>
      </div>
      {items.map((g, i) => (
        <div key={i} className="flex gap-2">
          <input
            value={g.command}
            onChange={(e) => update(i, "command", e.target.value)}
            placeholder="Command"
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs"
          />
          <input
            value={g.message}
            onChange={(e) => update(i, "message", e.target.value)}
            placeholder="Message (optional)"
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs"
          />
          <button onClick={() => remove(i)} className="text-xs text-red-400 hover:text-red-300">
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function StepEditForm({
  form,
  aliases,
  onChange,
  onSave,
  onCancel,
  extraBefore,
}: {
  form: {
    name: string;
    content: string;
    gates: Gate[];
    ifs: Gate[];
    agent_alias: string;
    step_type: string;
    allow_max: boolean;
    max_gate_retries: number;
  };
  aliases: AgentAlias[];
  onChange: (updates: Partial<typeof form>) => void;
  onSave: () => void;
  onCancel: () => void;
  extraBefore?: ReactNode;
}) {
  return (
    <div className="p-5 space-y-4">
      <div>
        <label className="text-xs text-gray-400 font-medium block mb-1">Name</label>
        <input
          value={form.name}
          onChange={(e) => onChange({ name: e.target.value })}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {extraBefore}

      <div>
        <label className="text-xs text-gray-400 font-medium block mb-1">Content (Markdown)</label>
        <textarea
          value={form.content}
          onChange={(e) => onChange({ content: e.target.value })}
          rows={12}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
        />
      </div>

      <GateEditor
        label="IF Conditions"
        subtitle="All must exit 0 or step is skipped"
        addLabel="+ Add if"
        items={form.ifs}
        onChange={(ifs) => onChange({ ifs })}
      />

      <GateEditor
        label="Gates"
        subtitle="Shell commands that must exit 0 before advancing"
        addLabel="+ Add gate"
        items={form.gates}
        onChange={(gates) => onChange({ gates })}
      />

      <div className="pl-3 border-l border-gray-700 space-y-3">
          <div>
            <label className="text-xs text-gray-400 font-medium block mb-1">Max Retries</label>
            <input
              type="number"
              value={form.max_gate_retries}
              onChange={(e) => onChange({ max_gate_retries: parseInt(e.target.value) || 0 })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm w-20"
            />
            <p className="text-xs text-gray-600 mt-1">
              If a gate fails, the step is re-run by the agent. This sets how many times that cycle repeats before the run is marked as failed.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-400">
            <input
              type="checkbox"
              checked={form.allow_max}
              onChange={(e) => onChange({ allow_max: e.target.checked })}
              className="rounded"
            />
            Allow max
          </label>
          <p className="text-xs text-gray-600">
            On the final retry, escalate to the <span className="text-gray-400 font-mono">max</span> alias (highest-capability model) instead of the step's default alias.
          </p>
        </div>

      <div className="flex items-center gap-4">
        <div>
          <label className="text-xs text-gray-400 font-medium block mb-1">Step Type</label>
          <select
            value={form.step_type}
            onChange={(e) => onChange({ step_type: e.target.value })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
          >
            <option value="agent">Agent</option>
            <option value="manual">Manual</option>
            <option value="prompt">Prompt</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 font-medium block mb-1">Agent Alias</label>
          <select
            value={form.agent_alias}
            onChange={(e) => onChange({ agent_alias: e.target.value })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
          >
            {aliases.map((a) => (
              <option key={a.name} value={a.name}>
                {a.name} ({a.agent}/{a.model})
              </option>
            ))}
          </select>
        </div>
      </div>
      {form.step_type !== "agent" && (
        <p className="text-xs text-amber-500/80">
          {form.step_type === "manual"
            ? "Agent will prepare instructions, then the step waits for user to confirm completion."
            : "Agent will formulate a question, then the step waits for user to provide an answer."}
        </p>
      )}

      <div className="text-xs text-amber-500 font-mono">
        Variables: {VARIABLES.join(" ")}
      </div>

      <div className="flex gap-3">
        <button onClick={onSave} className="text-xs text-blue-400 hover:text-blue-300">
          Save
        </button>
        <button onClick={onCancel} className="text-xs text-gray-500 hover:text-gray-300">
          Cancel
        </button>
      </div>
    </div>
  );
}

export function FlowEditorView() {
  const { flowId } = useParams<{ flowId: string }>();
  const navigate = useNavigate();
  const { reload, setSelectedProjectId } = useApp();

  const [flow, setFlow] = useState<Flow | null>(null);
  const [editingMeta, setEditingMeta] = useState(false);
  const [metaForm, setMetaForm] = useState({ name: "", description: "" });
  const [editingStep, setEditingStep] = useState<string | null>(null);
  const [stepForm, setStepForm] = useState({
    name: "", content: "", gates: [] as Gate[], ifs: [] as Gate[],
    agent_alias: "standard", step_type: "agent", allow_max: false, max_gate_retries: 3,
  });
  const [showAddStep, setShowAddStep] = useState(false);
  const [newStep, setNewStep] = useState({
    name: "", content: "", position: "", gates: [] as Gate[], ifs: [] as Gate[],
    agent_alias: "standard", step_type: "agent", allow_max: false, max_gate_retries: 3,
  });
  const [aliases, setAliases] = useState<AgentAlias[]>([]);
  const [localOrder, setLocalOrder] = useState<string[]>([]);
  const dragId = useRef<string | null>(null);
  const dragOverId = useRef<string | null>(null);

  const load = useCallback(async () => {
    if (!flowId) return;
    const [f, al] = await Promise.all([api.getFlow(flowId), api.listAgentAliases()]);
    setFlow(f);
    setSelectedProjectId(f.project_id);
    setMetaForm({ name: f.name, description: f.description || "" });
    setAliases(al);
    setLocalOrder([...f.steps].sort((a, b) => a.position - b.position).map((s) => s.id));
  }, [flowId]);

  useEffect(() => {
    load();
  }, [load]);

  const saveMeta = async () => {
    if (!flow) return;
    await api.updateFlow(flow.id, { name: metaForm.name, description: metaForm.description });
    setEditingMeta(false);
    load();
    reload();
  };

  const startEditStep = (step: FlowStep) => {
    setEditingStep(step.id);
    setStepForm({
      name: step.name,
      content: step.content || "",
      gates: (step.gates || []).map((g) => ({ ...g })),
      ifs: (step.ifs || []).map((g) => ({ ...g })),
      agent_alias: step.agent_alias || "standard",
      step_type: step.step_type || "agent",
      allow_max: step.allow_max || false,
      max_gate_retries: step.max_gate_retries ?? 3,
    });
  };

  const saveStep = async (stepId: string) => {
    if (!flow) return;
    await api.updateStep(flow.id, stepId, {
      name: stepForm.name,
      content: stepForm.content,
      gates: stepForm.gates.filter((g) => g.command.trim()),
      ifs: stepForm.ifs.filter((g) => g.command.trim()),
      agent_alias: stepForm.agent_alias,
      step_type: stepForm.step_type,
      allow_max: stepForm.allow_max,
      max_gate_retries: stepForm.max_gate_retries,
    });
    setEditingStep(null);
    load();
  };

  const addStep = async () => {
    if (!flow) return;
    const body: Record<string, unknown> = {
      name: newStep.name,
      content: newStep.content,
      agent_alias: newStep.agent_alias,
      step_type: newStep.step_type,
      allow_max: newStep.allow_max,
      max_gate_retries: newStep.max_gate_retries,
    };
    const gates = newStep.gates.filter((g) => g.command.trim());
    const ifs = newStep.ifs.filter((g) => g.command.trim());
    if (gates.length) body.gates = gates;
    if (ifs.length) body.ifs = ifs;
    if (newStep.position) body.position = parseInt(newStep.position);
    await api.addStep(flow.id, body);
    setNewStep({ name: "", content: "", position: "", gates: [], ifs: [], agent_alias: "standard", step_type: "agent", allow_max: false, max_gate_retries: 3 });
    setShowAddStep(false);
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

  const duplicateFlow = async () => {
    if (!flow) return;
    const newName = prompt("Name for the copy:", flow.name + "-copy");
    if (!newName) return;
    try {
      const created = await api.createFlow(flow.project_id, { name: newName, copy_from: flow.name });
      reload();
      navigate(`/flow-editor/${created.id}`);
    } catch (e: unknown) {
      alert("Error: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const stepMap = flow ? Object.fromEntries(flow.steps.map((s) => [s.id, s])) : {};
  const sortedSteps = localOrder.map((id) => stepMap[id]).filter(Boolean) as FlowStep[];

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* Back */}
      <button
        onClick={() => flow ? navigate(`/project/${flow.project_id}/flows`) : navigate("/")}
        className="text-xs text-gray-500 hover:text-gray-300 mb-4 block"
      >
        &larr; Flows
      </button>

      {/* Flow header */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl px-6 py-4 mb-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            {!editingMeta ? (
              <>
                <h2 className="text-xl font-semibold text-white">{flow?.name || "Loading..."}</h2>
                {flow?.description && (
                  <p className="text-sm text-gray-400 mt-1">{flow.description}</p>
                )}
              </>
            ) : (
              <div className="space-y-2">
                <input
                  value={metaForm.name}
                  onChange={(e) => setMetaForm({ ...metaForm, name: e.target.value })}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-64"
                />
                <input
                  value={metaForm.description}
                  onChange={(e) => setMetaForm({ ...metaForm, description: e.target.value })}
                  placeholder="Description"
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-full"
                />
                <div className="flex gap-3">
                  <button onClick={saveMeta} className="text-xs text-blue-400 hover:text-blue-300">
                    Save
                  </button>
                  <button onClick={() => setEditingMeta(false)} className="text-xs text-gray-500 hover:text-gray-300">
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
          {!editingMeta && (
            <div className="flex items-center gap-3 ml-4">
              <button onClick={() => setEditingMeta(true)} className="text-xs text-gray-400 hover:text-gray-200">
                Edit
              </button>
              <button onClick={duplicateFlow} className="text-xs text-gray-400 hover:text-gray-200">
                Duplicate
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Steps section */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Steps ({sortedSteps.length})
        </h3>
        <button
          onClick={() => setShowAddStep(true)}
          className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition"
        >
          + Add Step
        </button>
      </div>

      {/* Add Step Form */}
      {showAddStep && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl mb-3 overflow-hidden">
          <StepEditForm
            form={newStep}
            aliases={aliases}
            onChange={(updates) => setNewStep((s) => ({ ...s, ...updates }))}
            onSave={addStep}
            onCancel={() => setShowAddStep(false)}
            extraBefore={
              <input
                value={newStep.position}
                onChange={(e) => setNewStep({ ...newStep, position: e.target.value })}
                placeholder="Position (optional, leave empty for end)"
                type="number"
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-64"
              />
            }
          />
        </div>
      )}

      {/* Steps list */}
      <div className="space-y-2">
        {sortedSteps.map((step, i) => (
          <div
            key={step.id}
            className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden transition-opacity"
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
            {editingStep === step.id ? (
              <StepEditForm
                form={stepForm}
                aliases={aliases}
                onChange={(updates) => setStepForm((s) => ({ ...s, ...updates }))}
                onSave={() => saveStep(step.id)}
                onCancel={() => setEditingStep(null)}
              />
            ) : (
              <div className="px-4 py-3 flex items-start gap-3">
                {/* Drag handle */}
                <div
                  draggable
                  onDragStart={() => { dragId.current = step.id; dragOverId.current = step.id; }}
                  onDragEnd={() => {
                    reorderSteps(localOrder);
                    dragId.current = null;
                    dragOverId.current = null;
                  }}
                  className="mt-1 shrink-0 cursor-grab active:cursor-grabbing text-gray-600 hover:text-gray-400 select-none px-0.5"
                  title="Drag to reorder"
                >
                  ⠿
                </div>

                {/* Number */}
                <span className="text-xs text-gray-600 font-mono w-4 shrink-0 mt-0.5">{i + 1}</span>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-medium text-white">{step.name}</h4>
                      {step.step_type && step.step_type !== "agent" && (
                        <span className={`text-[10px] ${step.step_type === "manual" ? "text-amber-400" : "text-blue-400"}`}>
                          {step.step_type}
                        </span>
                      )}
                      {step.agent_alias && (
                        <span className="text-[10px] text-cyan-400">{step.agent_alias}</span>
                      )}
                      {step.allow_max && <span className="text-[10px] text-yellow-400">max</span>}
                      {step.max_gate_retries !== 3 && (
                        <span className="text-[10px] text-gray-500">retries:{step.max_gate_retries}</span>
                      )}
                      {step.gates?.length > 0 && <span className="text-[10px] text-orange-400">gates</span>}
                      {step.ifs?.length > 0 && <span className="text-[10px] text-purple-400">if</span>}
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <button
                        onClick={() => startEditStep(step)}
                        className="text-xs text-blue-400 hover:text-blue-300"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => removeStep(step.id)}
                        className="text-xs text-red-500 hover:text-red-400"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                  {step.content && (
                    <p className="text-xs text-gray-500 font-mono mt-1 truncate">
                      {step.content.slice(0, 80).replace(/\n/g, " ")}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}

        {sortedSteps.length === 0 && !showAddStep && (
          <div className="text-gray-500 text-center py-8">No steps yet</div>
        )}
      </div>

      {/* Footer note */}
      {sortedSteps.length > 0 && (
        <p className="text-xs text-gray-600 mt-4 text-center">
          System steps <span className="font-mono">start</span> (beginning) and{" "}
          <span className="font-mono">complete</span> (end) are auto-injected and not shown here.
        </p>
      )}
    </div>
  );
}
