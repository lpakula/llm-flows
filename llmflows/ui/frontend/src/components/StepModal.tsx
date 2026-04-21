import { useState } from "react";
import type { Gate, AgentAlias, SkillInfo, ToolConfig, StepType } from "@/api/types";

const STEP_TYPES: { value: StepType; label: string; desc: string }[] = [
  { value: "agent", label: "Agent", desc: "Pi-powered LLM with read/write/shell tools" },
  { value: "code", label: "Code", desc: "Coding agent (Cursor, Claude Code, etc.)" },
  { value: "hitl", label: "HITL (human in the loop)", desc: "LLM + human approval" },
];

const VARIABLES = [
  { token: "{{run.id}}", desc: "Current run ID" },
  { token: "{{flow.name}}", desc: "Flow name" },
  { token: "{{run.dir}}", desc: "Step artifacts directory" },
  { token: "{{flow.dir}}", desc: "Persistent flow directory (cross-run)" },
  { token: "{{steps.<name>.user_response}}", desc: "HITL step response" },
];

interface StepFormData {
  name: string;
  content: string;
  gates: Gate[];
  ifs: Gate[];
  agent_alias: string;
  step_type: string;
  allow_max: boolean;
  max_gate_retries: number;
  skills: string[];
  tools: string[];
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">{children}</h3>;
}

function GateRow({
  gate,
  onUpdate,
  onRemove,
}: {
  gate: Gate;
  onUpdate: (field: keyof Gate, value: string) => void;
  onRemove: () => void;
}) {
  return (
    <div className="group flex items-start gap-2 bg-gray-800/50 rounded-lg p-2.5">
      <div className="flex-1 min-w-0 space-y-1.5">
        <input
          value={gate.command}
          onChange={(e) => onUpdate("command", e.target.value)}
          placeholder="Command"
          className="w-full bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
        />
        <input
          value={gate.message}
          onChange={(e) => onUpdate("message", e.target.value)}
          placeholder="Failure message (optional)"
          className="w-full bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
        />
      </div>
      <button
        onClick={onRemove}
        className="mt-1.5 p-1 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

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
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <div className="flex items-baseline gap-2">
          <SectionLabel>{label}</SectionLabel>
          <span className="text-[10px] text-gray-600 normal-case tracking-normal">{subtitle}</span>
        </div>
        <button onClick={add} className="text-[11px] text-blue-400 hover:text-blue-300 transition-colors">
          {addLabel}
        </button>
      </div>
      {items.length > 0 && (
        <div className="space-y-2">
          {items.map((g, i) => (
            <GateRow key={i} gate={g} onUpdate={(f, v) => update(i, f, v)} onRemove={() => remove(i)} />
          ))}
        </div>
      )}
    </div>
  );
}

function StepSkillPicker({
  skills,
  selected,
  onChange,
}: { skills: SkillInfo[]; selected: string[]; onChange: (next: string[]) => void }) {
  const toggle = (name: string) => {
    if (selected.includes(name)) onChange(selected.filter((s) => s !== name));
    else onChange([...selected, name]);
  };
  if (skills.length === 0) return null;
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <SectionLabel>Skills</SectionLabel>
        <span className="text-[10px] text-gray-600 normal-case tracking-normal">Click to attach/detach</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {skills.map((s) => {
          const active = selected.includes(s.name);
          return (
            <button
              key={s.name}
              onClick={() => toggle(s.name)}
              className={`px-2.5 py-1 rounded-md text-xs font-mono border transition-all cursor-pointer ${
                active
                  ? "bg-blue-500/15 text-blue-300 border-blue-500/30"
                  : "border-gray-700/60 text-gray-500 hover:border-gray-500 hover:text-gray-300"
              }`}
            >
              {s.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StepToolPicker({
  tools,
  selected,
  onChange,
}: { tools: ToolConfig[]; selected: string[]; onChange: (next: string[]) => void }) {
  const toggle = (id: string) => {
    if (selected.includes(id)) onChange(selected.filter((t) => t !== id));
    else onChange([...selected, id]);
  };
  if (tools.length === 0) return null;
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <SectionLabel>Tools</SectionLabel>
        <span className="text-[10px] text-gray-600 normal-case tracking-normal">Click to attach/detach</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {tools.map((t) => {
          const active = selected.includes(t.id);
          return (
            <button
              key={t.id}
              onClick={() => toggle(t.id)}
              className={`px-2.5 py-1 rounded-md text-xs font-mono border transition-all cursor-pointer ${
                active
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                  : "border-gray-700/60 text-gray-500 hover:border-gray-500 hover:text-gray-300"
              }`}
            >
              {t.name}
              {!t.enabled && active && (
                <span className="ml-1 text-[10px] text-amber-400">(off)</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function VariablesRef() {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg bg-gray-800/40 border border-gray-800">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 text-[11px] text-gray-500 hover:text-gray-400 transition-colors"
      >
        <span className="font-medium">Available variables</span>
        <svg
          className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="px-3 pb-2.5 grid grid-cols-2 gap-x-4 gap-y-1">
          {VARIABLES.map((v) => (
            <div key={v.token} className="flex items-baseline gap-2 py-0.5">
              <code className="text-[11px] text-amber-400/80 font-mono whitespace-nowrap">{v.token}</code>
              <span className="text-[10px] text-gray-600 truncate">{v.desc}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function StepModal({
  title,
  initialData,
  aliases,
  skills,
  tools,
  onSave,
  onClose,
}: {
  title: string;
  initialData: StepFormData;
  aliases: AgentAlias[];
  skills: SkillInfo[];
  tools: ToolConfig[];
  onSave: (data: StepFormData) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<StepFormData>({ ...initialData });
  const onChange = (updates: Partial<StepFormData>) => setForm((s) => ({ ...s, ...updates }));
  const st = form.step_type as StepType;
  const aliasType = st === "code" ? "code" : "pi";
  const filteredAliases = aliases.filter((a) => a.type === aliasType);
  const hasGates = form.gates.length > 0;

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-gray-900 rounded-2xl border border-gray-700/60 w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between shrink-0">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 transition-colors p-1">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {/* Name */}
          <div>
            <label className="text-[11px] text-gray-400 font-medium block mb-1">Name</label>
            <input
              value={form.name}
              onChange={(e) => onChange({ name: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40"
            />
          </div>

          {/* Content */}
          <div>
            <label className="text-[11px] text-gray-400 font-medium block mb-1">Content (Markdown)</label>
            <textarea
              value={form.content}
              onChange={(e) => onChange({ content: e.target.value })}
              rows={10}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 resize-y"
            />
          </div>

          {/* Type + Alias */}
          <div>
            <div className="flex items-end gap-3">
              <div>
                <label className="text-[11px] text-gray-400 font-medium block mb-1">Type</label>
                <select
                  value={form.step_type}
                  onChange={(e) => onChange({ step_type: e.target.value })}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                >
                  {STEP_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] text-gray-400 font-medium block mb-1">Alias</label>
                <select
                  value={form.agent_alias}
                  onChange={(e) => onChange({ agent_alias: e.target.value })}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                >
                  {filteredAliases.length > 0 ? (
                    filteredAliases.map((a) => (
                      <option key={a.id} value={a.name}>
                        {a.name} ({a.agent}/{a.model})
                      </option>
                    ))
                  ) : (
                    <option value="normal">normal (not configured)</option>
                  )}
                </select>
              </div>
            </div>
            <p className="text-[10px] text-gray-600 mt-1">{STEP_TYPES.find((t) => t.value === st)?.desc}</p>
          </div>

          {/* Skills */}
          <div className="border-t border-gray-800" />
          <StepSkillPicker skills={skills} selected={form.skills} onChange={(s) => onChange({ skills: s })} />

          {/* Tools */}
          <StepToolPicker tools={tools} selected={form.tools} onChange={(t) => onChange({ tools: t })} />

          {/* Divider */}
          <div className="border-t border-gray-800" />

          {/* IF Conditions */}
          <GateEditor
            label="IF Conditions"
            subtitle="All must exit 0 or step is skipped"
            addLabel="+ Add if"
            items={form.ifs}
            onChange={(ifs) => onChange({ ifs })}
          />

          {/* Gates */}
          <GateEditor
            label="Gates"
            subtitle="Shell commands that must exit 0 before advancing"
            addLabel="+ Add gate"
            items={form.gates}
            onChange={(gates) => onChange({ gates })}
          />

          {/* Gate options */}
          {hasGates && (
            <div className="flex items-center gap-5 pl-3 border-l-2 border-gray-700/60">
              <div className="flex items-center gap-2">
                <label className="text-[11px] text-gray-400 font-medium">Max Retries</label>
                <input
                  type="number"
                  value={form.max_gate_retries}
                  onChange={(e) => onChange({ max_gate_retries: parseInt(e.target.value) || 0 })}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-16 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
                />
              </div>
              <label className="flex items-center gap-1.5 text-[11px] text-gray-400 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={form.allow_max}
                  onChange={(e) => onChange({ allow_max: e.target.checked })}
                  className="rounded border-gray-600"
                />
                Allow max
              </label>
            </div>
          )}

          {/* Variables reference */}
          <div className="border-t border-gray-800" />
          <VariablesRef />
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-gray-800 flex justify-end gap-3 shrink-0">
          <button onClick={onClose} className="px-4 py-1.5 text-xs text-gray-400 hover:text-gray-200 transition-colors">
            Cancel
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={!form.name.trim()}
            className="px-5 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-40 transition-colors"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
