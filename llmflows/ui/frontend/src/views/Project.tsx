import { useState, useEffect, useCallback, useRef, useMemo, Fragment } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { useAutoResize } from "@/hooks/useAutoResize";
import { useImagePaste } from "@/hooks/useImagePaste";
import type { Task, Flow } from "@/api/types";
import { typeColor, statusBadge, statusDot, displayStatus, duration, formatSeconds } from "@/lib/format";
import { RunModal } from "@/components/RunModal";

// ── Status definitions ────────────────────────────────────────────────────────

const TASK_STATUSES = [
  { key: "backlog",     label: "Backlog",     dot: "bg-gray-500",   text: "text-gray-400" },
  { key: "queue",       label: "Queue",       dot: "bg-blue-500",   text: "text-blue-400" },
  { key: "in_progress", label: "In Progress", dot: "bg-yellow-400", text: "text-yellow-400" },
  { key: "completed",   label: "Completed",   dot: "bg-green-500",  text: "text-green-400" },
] as const;

type TaskStatusKey = typeof TASK_STATUSES[number]["key"];

function statusMeta(key: string) {
  return TASK_STATUSES.find((s) => s.key === key) ?? TASK_STATUSES[0];
}

// ── Status picker dropdown ────────────────────────────────────────────────────

function StatusPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (s: TaskStatusKey) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const meta = statusMeta(value);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
        title="Change status"
      >
        <span className={`w-2 h-2 rounded-full shrink-0 ${meta.dot}`} />
      </button>
      {open && (
        <ul className="absolute z-50 left-0 top-5 w-36 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1">
          {TASK_STATUSES.map((s) => (
            <li key={s.key}>
              <button
                onClick={() => { onChange(s.key); setOpen(false); }}
                className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 hover:bg-gray-700 transition-colors ${s.key === value ? "text-white" : "text-gray-400"}`}
              >
                <span className={`w-2 h-2 rounded-full shrink-0 ${s.dot}`} />
                {s.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


// ── Task row (list view) ──────────────────────────────────────────────────────

function TaskRow({
  task,
  onDelete,
  onRun,
  onStop,
  onClick,
}: {
  task: Task;
  onDelete: (id: string) => void;
  onRun: (task: Task) => void;
  onStop: (task: Task) => void;
  onClick: (id: string) => void;
}) {
  return (
    <tr
      className="border-b border-gray-800/80 last:border-0 hover:bg-gray-800/40 cursor-pointer transition-colors group"
      onClick={() => onClick(task.id)}
    >
      <td className="w-6" />
      <td className="w-6" />
      <td className="pr-2 py-2.5 min-w-0">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-sm text-white whitespace-nowrap shrink-0">{task.name}</span>
          {task.description && (
            <span className="text-xs text-gray-500 truncate max-w-xs">{task.description}</span>
          )}
        </div>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        <span className="text-xs text-gray-500 font-mono">{task.id}</span>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        <span className={`text-[10px] uppercase font-medium ${typeColor(task.type)}`}>{task.type}</span>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap text-cyan-400 text-xs">
        {task.default_flow_name || <span className="text-gray-700">—</span>}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap text-gray-500 text-xs tabular-nums">
        {task.run_count > 0
          ? <span>{task.run_count} <span className="text-gray-600">runs</span></span>
          : <span className="text-gray-700">—</span>}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        {task.last_run_status ? (() => {
          const fakeRun = { status: task.last_run_status!, outcome: task.last_run_outcome };
          const label = displayStatus(fakeRun);
          const dur = task.last_run_duration_seconds != null
            ? formatSeconds(task.last_run_duration_seconds)
            : duration(task.last_run_started_at, task.last_run_completed_at);
          return (
            <div className="flex items-center gap-1.5">
              <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ${statusBadge(label)}`}>
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(task.last_run_status!, task.last_run_outcome)}`} />
                {label}
              </span>
              {dur !== "-" && dur !== "—" && <span className="text-[10px] text-gray-600 tabular-nums">{dur}</span>}
            </div>
          );
        })() : <span className="text-gray-700">—</span>}
      </td>
      <td className="px-3 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-end gap-3">
          {task.task_status === "queue" || task.task_status === "in_progress" ? (
            <button
              onClick={() => onStop(task)}
              className="text-xs text-red-400 hover:text-red-300 transition"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={() => onRun(task)}
              className="text-xs text-blue-400 hover:text-blue-300 transition"
            >
              Run
            </button>
          )}
          <button
            onClick={() => onDelete(task.id)}
            className="text-xs text-gray-700 hover:text-red-400 transition opacity-0 group-hover:opacity-100"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}

// ── Task card (kanban view) ───────────────────────────────────────────────────

function TaskCard({
  task,
  onDelete,
  onRun,
  onStop,
  onClick,
}: {
  task: Task;
  onDelete: (id: string) => void;
  onRun: (task: Task) => void;
  onStop: (task: Task) => void;
  onClick: (id: string) => void;
}) {
  return (
    <div
      onClick={() => onClick(task.id)}
      className="bg-gray-900 border border-gray-800 rounded-xl p-3 hover:border-gray-600 cursor-pointer transition-colors group"
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`text-[10px] uppercase font-medium shrink-0 ${typeColor(task.type)}`}>{task.type}</span>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(task.id); }}
          className="text-xs text-gray-700 hover:text-red-400 transition opacity-0 group-hover:opacity-100 shrink-0"
        >
          ×
        </button>
      </div>
      <div className="text-sm text-white mb-1">{task.name}</div>
      <div className="text-xs text-gray-500 line-clamp-2 h-8 mb-2">
        {task.description || ""}
      </div>
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-800">
        <span className="text-xs text-cyan-400">{task.default_flow_name || ""}</span>
        <div className="flex items-center gap-2">
          {task.run_count > 0 && (
            <span className="text-xs text-gray-600">{task.run_count} runs</span>
          )}
          {task.last_run_status && (() => {
            const fakeRun = { status: task.last_run_status!, outcome: task.last_run_outcome };
            const label = displayStatus(fakeRun);
            const dur = task.last_run_duration_seconds != null
              ? formatSeconds(task.last_run_duration_seconds)
              : duration(task.last_run_started_at, task.last_run_completed_at);
            return (
              <>
                <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ${statusBadge(label)}`}>
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(task.last_run_status!, task.last_run_outcome)}`} />
                  {label}
                </span>
                {dur !== "-" && dur !== "—" && <span className="text-[10px] text-gray-600 tabular-nums">{dur}</span>}
              </>
            );
          })()}
          {task.task_status === "queue" || task.task_status === "in_progress" ? (
            <button
              onClick={(e) => { e.stopPropagation(); onStop(task); }}
              className="text-xs text-red-400 hover:text-red-300 transition"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={(e) => { e.stopPropagation(); onRun(task); }}
              className="text-xs text-blue-400 hover:text-blue-300 transition"
            >
              Run
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// Render order for list/kanban sections
const SECTION_ORDER: TaskStatusKey[] = ["completed", "in_progress", "queue", "backlog"];
const KANBAN_ORDER: TaskStatusKey[] = ["backlog", "queue", "in_progress", "completed"];

// ── Main view ─────────────────────────────────────────────────────────────────

type ViewMode = "list" | "kanban";

export function ProjectView() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [tasks, setTasks] = useState<Task[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newTask, setNewTask] = useState({ title: "", description: "", type: "feature", default_flow_name: "", task_status: "backlog" as TaskStatusKey });
  const newTaskDescRef = useAutoResize(newTask.description);
  const newTaskSessionId = useMemo(() => crypto.randomUUID(), []);
  const setNewTaskDescription = useCallback((v: React.SetStateAction<string>) => {
    setNewTask((prev) => ({ ...prev, description: typeof v === "function" ? v(prev.description) : v }));
  }, []);
  const onNewTaskDescPaste = useImagePaste(newTaskSessionId, setNewTaskDescription);
  const [flows, setFlows] = useState<Flow[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>(() => (localStorage.getItem("tasks-view") as ViewMode) ?? "list");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ completed: true });
  const [runModalTask, setRunModalTask] = useState<Task | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      setTasks(await api.listTasks(projectId));
    } catch (e) {
      console.error("Project load error:", e);
    }
  }, [projectId]);

  useEffect(() => {
    load();
    if (projectId) {
      api.listFlows(projectId).then(setFlows).catch(() => setFlows([]));
    }
  }, [load, projectId]);

  useInterval(load, 5000);

  const setView = (mode: ViewMode) => {
    setViewMode(mode);
    localStorage.setItem("tasks-view", mode);
  };

  const createTask = async () => {
    if (!projectId) return;
    await api.createTask(projectId, {
      ...newTask,
      default_flow_name: newTask.default_flow_name || undefined,
    });
    setNewTask({ title: "", description: "", type: "feature", default_flow_name: "", task_status: "backlog" });
    setShowCreate(false);
    load();
  };

  const updateStatus = async (taskId: string, task_status: TaskStatusKey) => {
    setTasks((prev) => prev.map((t) => t.id === taskId ? { ...t, task_status } : t));
    await api.updateTask(taskId, { task_status });
  };

  const deleteTask = async (taskId: string) => {
    if (!confirm("Delete this task?")) return;
    await api.deleteTask(taskId);
    load();
  };

  const openTask = (taskId: string) => navigate(`/project/${projectId}/task/${taskId}`);

  const openRunModal = async (task: Task) => {
    if (flows.length === 0 && projectId) {
      api.listFlows(projectId).then(setFlows).catch(() => {});
    }
    setRunModalTask(task);
  };

  const submitRun = async (taskId: string, { flow, prompt, one_shot }: { flow: string; prompt: string; one_shot: boolean }) => {
    await api.startTask(taskId, { flow: flow || null, user_prompt: prompt, one_shot });
    load();
  };

  const stopTask = async (task: Task) => {
    if (!task.run_id) return;
    await api.stopRun(task.run_id);
    load();
  };

  const toggleCollapsed = (key: string) =>
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));

  const sortedTasks = [...tasks].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  const makeGroups = (order: TaskStatusKey[]) =>
    order.map((key) => {
      const meta = TASK_STATUSES.find((s) => s.key === key)!;
      return {
        ...meta,
        tasks: sortedTasks.filter((t) => (t.task_status || "backlog") === key),
      };
    });

  const grouped = makeGroups(SECTION_ORDER);
  const kanbanGrouped = makeGroups(KANBAN_ORDER);

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Tasks</h2>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex items-center bg-gray-800 border border-gray-700 rounded-lg p-0.5">
            <button
              onClick={() => setView("list")}
              title="List view"
              className={`px-2.5 py-1 rounded text-xs transition-colors ${viewMode === "list" ? "bg-gray-600 text-white" : "text-gray-500 hover:text-gray-300"}`}
            >
              ☰
            </button>
            <button
              onClick={() => setView("kanban")}
              title="Kanban view"
              className={`px-2.5 py-1 rounded text-xs transition-colors ${viewMode === "kanban" ? "bg-gray-600 text-white" : "text-gray-500 hover:text-gray-300"}`}
            >
              ⊞
            </button>
          </div>
          <button
            onClick={() => setShowCreate((v) => !v)}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition"
          >
            + New Task
          </button>
        </div>
      </div>

      {/* Inline create form */}
      {showCreate && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6 space-y-3">
          <input
            value={newTask.title}
            onChange={(e) => setNewTask({ ...newTask, title: e.target.value })}
            placeholder="Task title"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            autoFocus
            onKeyDown={(e) => e.key === "Escape" && setShowCreate(false)}
          />
          <textarea
            ref={newTaskDescRef}
            value={newTask.description}
            onChange={(e) => setNewTask({ ...newTask, description: e.target.value })}
            onPaste={onNewTaskDescPaste}
            placeholder="Task description"
            rows={3}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none overflow-hidden"
          />
          <div className="flex gap-2 flex-wrap">
            <select
              value={newTask.type}
              onChange={(e) => setNewTask({ ...newTask, type: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none"
            >
              <option value="feature">Feature</option>
              <option value="fix">Fix</option>
              <option value="refactor">Refactor</option>
              <option value="chore">Chore</option>
            </select>
            <select
              value={newTask.default_flow_name}
              onChange={(e) => setNewTask({ ...newTask, default_flow_name: e.target.value })}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none min-w-[140px]"
            >
              <option value="">No default flow</option>
              {flows.map((f) => (
                <option key={f.id} value={f.name}>{f.name}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button
              onClick={createTask}
              disabled={!newTask.title.trim()}
              className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40"
            >
              Create
            </button>
            <button onClick={() => setShowCreate(false)} className="text-xs text-gray-500 hover:text-gray-300">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── List view ─────────────────────────────────────────── */}
      {viewMode === "list" && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-gray-800 text-[10px] uppercase tracking-wide text-gray-600">
                <th className="w-6"></th>
                <th className="w-6"></th>
                <th className="pr-2 py-2 font-medium">Task</th>
                <th className="px-3 py-2 font-medium whitespace-nowrap">ID</th>
                <th className="px-3 py-2 font-medium whitespace-nowrap">Type</th>
                <th className="px-3 py-2 font-medium">Flow</th>
                <th className="px-3 py-2 font-medium">Runs</th>
                <th className="px-3 py-2 font-medium whitespace-nowrap">Last Run</th>
                <th className="px-3 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {grouped.map((group) => {
                const isCollapsed = collapsed[group.key];
                return (
                  <Fragment key={group.key}>
                    <tr
                      className="border-b border-gray-800 bg-gray-800/40 hover:bg-gray-800/60 cursor-pointer transition-colors"
                      onClick={() => toggleCollapsed(group.key)}
                    >
                      <td className="px-3 py-2 w-6">
                        <span className={`text-[9px] transition-transform inline-block ${isCollapsed ? "" : "rotate-90"}`}>▶</span>
                      </td>
                      <td className="py-2 pr-3 w-6">
                        <span className={`w-2 h-2 rounded-full inline-block ${group.dot}`} />
                      </td>
                      <td colSpan={7} className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-300">{group.label}</span>
                          <span className="text-xs text-gray-600">{group.tasks.length}</span>
                        </div>
                      </td>
                    </tr>
                    {!isCollapsed && (
                      group.tasks.length === 0 ? (
                        <tr>
                          <td colSpan={9} className="px-4 py-4 text-center text-gray-700">
                            No tasks
                          </td>
                        </tr>
                      ) : (
                        group.tasks.map((task) => (
                          <TaskRow
                            key={task.id}
                            task={task}
                            onDelete={deleteTask}
                            onRun={openRunModal}
                            onStop={stopTask}
                            onClick={openTask}
                          />
                        ))
                      )
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Kanban view ───────────────────────────────────────── */}
      {viewMode === "kanban" && (
        <div className="grid gap-4 items-start" style={{ gridTemplateColumns: `repeat(${kanbanGrouped.length}, minmax(0, 1fr))` }}>
          {kanbanGrouped.map((group) => (
            <div key={group.key} className="min-w-0">
              {/* Column header */}
              <div className="flex items-center gap-2 mb-3 px-1">
                <span className={`w-2 h-2 rounded-full shrink-0 ${group.dot}`} />
                <span className="text-sm font-medium text-gray-300">{group.label}</span>
                <span className="text-xs text-gray-600">{group.tasks.length}</span>
              </div>
              {/* Cards */}
              <div className="space-y-2">
                {group.tasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    onDelete={deleteTask}
                    onRun={openRunModal}
                    onStop={stopTask}
                    onClick={openTask}
                  />
                ))}
                {group.tasks.length === 0 && (
                  <div className="text-xs text-gray-700 text-center py-6 border border-dashed border-gray-800 rounded-xl">
                    Empty
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {runModalTask && (
        <RunModal
          task={runModalTask}
          flows={flows}
          onClose={() => setRunModalTask(null)}
          onSubmit={submitRun}
        />
      )}
    </div>
  );
}
