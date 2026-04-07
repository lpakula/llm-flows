import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useApp } from "@/App";
import type { Flow, FlowStep, Gate, AgentAlias } from "@/api/types";

function GateEditor({
  label,
  items,
  onChange,
}: {
  label: string;
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
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500">{label}</span>
        <button onClick={add} className="text-xs text-blue-400 hover:text-blue-300">
          + Add
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
    agent_alias: "standard", allow_max: false, max_gate_retries: 3,
  });
  const [showAddStep, setShowAddStep] = useState(false);
  const [newStep, setNewStep] = useState({
    name: "", content: "", position: "", gates: [] as Gate[], ifs: [] as Gate[],
    agent_alias: "standard", allow_max: false, max_gate_retries: 3,
  });
  const [aliases, setAliases] = useState<AgentAlias[]>([]);

  const load = useCallback(async () => {
    if (!flowId) return;
    const [f, al] = await Promise.all([api.getFlow(flowId), api.listAgentAliases()]);
    setFlow(f);
    setSelectedProjectId(f.project_id);
    setMetaForm({ name: f.name, description: f.description || "" });
    setAliases(al);
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
      allow_max: newStep.allow_max,
      max_gate_retries: newStep.max_gate_retries,
    };
    const gates = newStep.gates.filter((g) => g.command.trim());
    const ifs = newStep.ifs.filter((g) => g.command.trim());
    if (gates.length) body.gates = gates;
    if (ifs.length) body.ifs = ifs;
    if (newStep.position) body.position = parseInt(newStep.position);
    await api.addStep(flow.id, body);
    setNewStep({ name: "", content: "", position: "", gates: [], ifs: [], agent_alias: "standard", allow_max: false, max_gate_retries: 3 });
    setShowAddStep(false);
    load();
  };

  const removeStep = async (stepId: string) => {
    if (!flow || !confirm("Remove this step?")) return;
    await api.deleteStep(flow.id, stepId);
    load();
  };

  const moveStep = async (stepId: string, direction: "up" | "down") => {
    if (!flow) return;
    const sorted = [...flow.steps].sort((a, b) => a.position - b.position);
    const ids = sorted.map((s) => s.id);
    const idx = ids.indexOf(stepId);
    if (direction === "up" && idx > 0) {
      [ids[idx - 1], ids[idx]] = [ids[idx], ids[idx - 1]];
    } else if (direction === "down" && idx < ids.length - 1) {
      [ids[idx], ids[idx + 1]] = [ids[idx + 1], ids[idx]];
    }
    await api.reorderSteps(flow.id, ids);
    load();
  };

  const duplicateFlow = async () => {
    if (!flow) return;
    const newName = prompt("Name for the copy:", flow.name + "-copy");
    if (!newName) return;
    try {
      const created = await api.createFlow({ name: newName, copy_from: flow.name });
      reload();
      navigate(`/flow-editor/${created.id}`);
    } catch (e: unknown) {
      alert("Error: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const sortedSteps = flow ? [...flow.steps].sort((a, b) => a.position - b.position) : [];

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => flow ? navigate(`/project/${flow.project_id}/flows`) : navigate("/")} className="text-xs text-gray-500 hover:text-gray-300">
            &larr; Flows
          </button>
          {!editingMeta ? (
            <>
              <h2 className="text-xl font-semibold">{flow?.name || "Loading..."}</h2>
              {flow?.description && <span className="text-xs text-gray-500">{flow.description}</span>}
              <button onClick={() => setEditingMeta(true)} className="text-xs text-gray-500 hover:text-blue-400">
                Edit
              </button>
            </>
          ) : (
            <>
              <input
                value={metaForm.name}
                onChange={(e) => setMetaForm({ ...metaForm, name: e.target.value })}
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <input
                value={metaForm.description}
                onChange={(e) => setMetaForm({ ...metaForm, description: e.target.value })}
                placeholder="Description"
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button onClick={saveMeta} className="text-xs text-blue-400">
                Save
              </button>
              <button onClick={() => setEditingMeta(false)} className="text-xs text-gray-500">
                Cancel
              </button>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={duplicateFlow} className="text-xs text-gray-500 hover:text-gray-300">
            Duplicate
          </button>
          <button onClick={() => setShowAddStep(true)} className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition">
            + Add Step
          </button>
        </div>
      </div>

      {/* Add Step Form */}
      {showAddStep && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-4 space-y-3">
          <input
            value={newStep.name}
            onChange={(e) => setNewStep({ ...newStep, name: e.target.value })}
            placeholder="Step name"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            autoFocus
          />
          <textarea
            value={newStep.content}
            onChange={(e) => setNewStep({ ...newStep, content: e.target.value })}
            placeholder="Step content (markdown prompt)"
            rows={6}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
          <input
            value={newStep.position}
            onChange={(e) => setNewStep({ ...newStep, position: e.target.value })}
            placeholder="Position (optional, leave empty for end)"
            type="number"
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-48"
          />
          <div className="flex items-center gap-4">
            <div>
              <label className="text-xs text-gray-500 block mb-1">Agent Alias</label>
              <select
                value={newStep.agent_alias}
                onChange={(e) => setNewStep({ ...newStep, agent_alias: e.target.value })}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
              >
                {aliases.map((a) => (
                  <option key={a.name} value={a.name}>{a.name} ({a.agent}/{a.model})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Max Retries</label>
              <input
                type="number"
                value={newStep.max_gate_retries}
                onChange={(e) => setNewStep({ ...newStep, max_gate_retries: parseInt(e.target.value) || 0 })}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm w-20"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-400 mt-4">
              <input
                type="checkbox"
                checked={newStep.allow_max}
                onChange={(e) => setNewStep({ ...newStep, allow_max: e.target.checked })}
                className="rounded"
              />
              Allow max
            </label>
          </div>
          <GateEditor label="Gates" items={newStep.gates} onChange={(gates) => setNewStep({ ...newStep, gates })} />
          <GateEditor label="If conditions" items={newStep.ifs} onChange={(ifs) => setNewStep({ ...newStep, ifs })} />
          <div className="flex gap-2">
            <button onClick={addStep} disabled={!newStep.name.trim()} className="text-xs text-blue-400 disabled:opacity-40">
              Add
            </button>
            <button onClick={() => setShowAddStep(false)} className="text-xs text-gray-500">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Steps */}
      <div className="space-y-2">
        {sortedSteps.map((step, i) => (
          <div key={step.id} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            {editingStep === step.id ? (
              <div className="p-4 space-y-3">
                <input
                  value={stepForm.name}
                  onChange={(e) => setStepForm({ ...stepForm, name: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <textarea
                  value={stepForm.content}
                  onChange={(e) => setStepForm({ ...stepForm, content: e.target.value })}
                  rows={10}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                />
                <div className="flex items-center gap-4">
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">Agent Alias</label>
                    <select
                      value={stepForm.agent_alias}
                      onChange={(e) => setStepForm({ ...stepForm, agent_alias: e.target.value })}
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                    >
                      {aliases.map((a) => (
                        <option key={a.name} value={a.name}>{a.name} ({a.agent}/{a.model})</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">Max Retries</label>
                    <input
                      type="number"
                      value={stepForm.max_gate_retries}
                      onChange={(e) => setStepForm({ ...stepForm, max_gate_retries: parseInt(e.target.value) || 0 })}
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm w-20"
                    />
                  </div>
                  <label className="flex items-center gap-2 text-sm text-gray-400 mt-4">
                    <input
                      type="checkbox"
                      checked={stepForm.allow_max}
                      onChange={(e) => setStepForm({ ...stepForm, allow_max: e.target.checked })}
                      className="rounded"
                    />
                    Allow max
                  </label>
                </div>
                <GateEditor label="Gates" items={stepForm.gates} onChange={(gates) => setStepForm({ ...stepForm, gates })} />
                <GateEditor label="If conditions" items={stepForm.ifs} onChange={(ifs) => setStepForm({ ...stepForm, ifs })} />
                <div className="flex gap-2">
                  <button onClick={() => saveStep(step.id)} className="text-xs text-blue-400">
                    Save
                  </button>
                  <button onClick={() => setEditingStep(null)} className="text-xs text-gray-500">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="px-5 py-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-600 font-mono w-6">{i + 1}</span>
                    <h4 className="text-sm font-medium text-white">{step.name}</h4>
                    {step.agent_alias && step.agent_alias !== "standard" && (
                      <span className="text-[10px] text-cyan-400">{step.agent_alias}</span>
                    )}
                    {step.allow_max && <span className="text-[10px] text-yellow-400">max</span>}
                    {step.max_gate_retries !== 3 && (
                      <span className="text-[10px] text-gray-500">retries:{step.max_gate_retries}</span>
                    )}
                    {(step.gates?.length > 0) && <span className="text-[10px] text-orange-400">gates</span>}
                    {(step.ifs?.length > 0) && <span className="text-[10px] text-purple-400">if</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => moveStep(step.id, "up")} disabled={i === 0} className="text-xs text-gray-600 hover:text-gray-400 disabled:opacity-20">
                      ↑
                    </button>
                    <button onClick={() => moveStep(step.id, "down")} disabled={i === sortedSteps.length - 1} className="text-xs text-gray-600 hover:text-gray-400 disabled:opacity-20">
                      ↓
                    </button>
                    <button onClick={() => startEditStep(step)} className="text-xs text-blue-400 hover:text-blue-300">
                      Edit
                    </button>
                    <button onClick={() => removeStep(step.id)} className="text-xs text-gray-600 hover:text-red-400">
                      Delete
                    </button>
                  </div>
                </div>
                {step.content && (
                  <pre className="text-xs text-gray-500 font-mono whitespace-pre-wrap max-h-32 overflow-y-auto">
                    {step.content}
                  </pre>
                )}
              </div>
            )}
          </div>
        ))}
        {sortedSteps.length === 0 && !showAddStep && (
          <div className="text-gray-500 text-center py-8">No steps yet</div>
        )}
      </div>
    </div>
  );
}
