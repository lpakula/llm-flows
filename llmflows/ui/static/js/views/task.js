/**
 * Task detail view -- run history + agent logs.
 */
function taskView() {
  return {
    task: null,
    runs: [],
    logEntries: [],
    logStreaming: false,
    expandedRun: null,
    streamingRunId: null,
    worktreePrefix: null,
    _logEventSource: null,
    runModal: false,
    runModalChain: [],
    runModalFlowSelect: '',
    runModalPrompt: '',
    runModalModel: '',
    runModalModels: [],
    runModalAgent: '',
    runModalAgents: [],
    runModalIsFirstRun: false,
    runModalProject: null,
    logsCopied: false,

    async init() {
      const tid = Alpine.store('router').params.taskId;
      if (!tid) return;
      await this.load(tid);
      this._interval = setInterval(() => this.refreshTask(tid), 5000);
    },

    destroy() {
      if (this._interval) clearInterval(this._interval);
      this.stopLogStream();
    },

    async load(tid) {
      try {
        const proj = Alpine.store('app').projects;
        let allTasksFlat = [];
        for (const p of proj) {
          const ts = await API.get(`/api/projects/${p.id}/tasks`);
          allTasksFlat.push(...ts);
        }
        this.task = allTasksFlat.find(t => t.id === tid) || null;

        if (this.task) {
          this.runs = await API.get(`/api/tasks/${tid}/runs`);
          this._resolveWorktreePrefix();
          const activeRun = this.runs.find(r => this.isRunActive(r));
          if (activeRun) {
            this.expandedRun = activeRun.id;
            this.viewRunLogs(activeRun.id);
          }
        }
      } catch (e) {
        console.error('Task load error:', e);
      }
    },

    async refreshTask(tid) {
      try {
        const proj = Alpine.store('app').projects;
        for (const p of proj) {
          const ts = await API.get(`/api/projects/${p.id}/tasks`);
          const found = ts.find(t => t.id === tid);
          if (found) {
            this.task = found;
            this.runs = await API.get(`/api/tasks/${tid}/runs`);
            break;
          }
        }
      } catch (e) {}
    },

    _resolveWorktreePrefix() {
      if (!this.task) return;
      const oldPrefix = this.worktreePrefix;
      this.worktreePrefix = this.task.worktree_path ? this.task.worktree_path + '/' : null;
      // If prefix just became available retroactively shorten already-parsed log entries
      if (!oldPrefix && this.worktreePrefix && this.logEntries.length > 0) {
        const prefix = this.worktreePrefix;
        this.logEntries = this.logEntries.map(e => ({
          ...e,
          text: e.text.split(prefix).join(''),
        }));
      }
    },

    _shorten(path) {
      if (!path) return '?';
      if (this.worktreePrefix && path.startsWith(this.worktreePrefix)) {
        return path.slice(this.worktreePrefix.length);
      }
      return path;
    },

    isRunActive(run) {
      return run.started_at && !run.completed_at;
    },

    get activeRun() {
      return this.runs.find(r => this.isRunActive(r)) || null;
    },

    runDisplayStatus(run) {
      if (run.status === 'completed' && run.outcome && run.outcome !== 'completed') {
        return run.outcome;
      }
      return run.status;
    },

    runStatusBadge(status) {
      return {
        queued: 'bg-blue-900/50 text-blue-300',
        running: 'bg-yellow-900/50 text-yellow-300',
        completed: 'bg-green-900/50 text-green-300',
        cancelled: 'bg-red-900/50 text-red-400',
        failed: 'bg-red-900/50 text-red-300',
        timeout: 'bg-orange-900/50 text-orange-300',
      }[status] || 'bg-gray-700 text-gray-300';
    },

    statusBadge(status) {
      return this.runStatusBadge(status);
    },

    outcomeBadge(outcome) {
      if (!outcome) return 'bg-gray-700 text-gray-300';
      return this.runStatusBadge(outcome);
    },

    toggleRun(runId) {
      if (this.expandedRun === runId) {
        this.expandedRun = null;
        if (this.streamingRunId === runId) {
          this.stopLogStream();
          this.streamingRunId = null;
        }
      } else {
        this.expandedRun = runId;
        const run = this.runs.find(r => r.id === runId);
        if (run && this.isRunActive(run)) {
          this.viewRunLogs(runId);
        }
      }
    },

    viewRunLogs(runId) {
      if (this.streamingRunId === runId) return;
      this.stopLogStream();
      this.streamingRunId = runId;
      this.logEntries = [];

      const run = this.runs.find(r => r.id === runId);
      if (run && run.log_path === 'inline') {
        this.logStreaming = false;
        this.logEntries.push({
          text: 'This run was started inline (e.g. from Cursor). Logs are managed by the calling agent.',
          cls: 'text-gray-500',
        });
        return;
      }

      this.logStreaming = true;
      const source = new EventSource(`/api/runs/${runId}/logs`);
      this._logEventSource = source;
      source.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          if (event.type === 'done') {
            this.logStreaming = false;
            source.close();
            return;
          }
          const entries = this.parseLogEvent(event);
          if (entries) {
            for (const entry of entries) {
              this.logEntries.push(entry);
            }
            if (this.logEntries.length > 500) {
              this.logEntries = this.logEntries.slice(-400);
            }
          }
        } catch {}
      };
      source.onerror = () => {
        this.logStreaming = false;
        source.close();
      };
    },

    stopLogStream() {
      if (this._logEventSource) {
        this._logEventSource.close();
        this._logEventSource = null;
      }
      this.logStreaming = false;
    },

    // --- Log parsing (mirrors CLI _print_event logic) ---

    _extractTool(tc) {
      for (const key of ['readToolCall', 'writeToolCall', 'editToolCall', 'shellToolCall',
                          'grepToolCall', 'globToolCall', 'listToolCall', 'deleteToolCall',
                          'updateTodosToolCall', 'function']) {
        if (tc[key]) return { name: key, data: tc[key] };
      }
      for (const [key, val] of Object.entries(tc)) {
        if (val && typeof val === 'object') return { name: key, data: val };
      }
      return { name: 'unknown', data: {} };
    },

    _describeToolStart(tc) {
      const { name, data } = this._extractTool(tc);
      const args = data.args || {};

      if (name === 'readToolCall') return `Read ${this._shorten(args.path)}`;
      if (name === 'writeToolCall') return `Write ${this._shorten(args.path)}`;
      if (name === 'editToolCall') return `Edit ${this._shorten(args.path)}`;
      if (name === 'shellToolCall') return `Shell: ${(args.command || '?').slice(0, 100)}`;
      if (name === 'grepToolCall') return `Grep: ${args.pattern || '?'}`;
      if (name === 'globToolCall') return `Glob: ${args.pattern || args.glob || '?'}`;
      if (name === 'listToolCall') return `List ${this._shorten(args.path)}`;
      if (name === 'deleteToolCall') return `Delete ${this._shorten(args.path)}`;
      if (name === 'updateTodosToolCall') {
        const todos = args.todos || [];
        return `Update todos (${todos.length} items)`;
      }
      if (name === 'function') {
        const fnName = data.name || 'tool';
        try {
          const fnArgs = JSON.parse(data.arguments || '{}');
          if (fnArgs.command) return `${fnName}: ${fnArgs.command.slice(0, 100)}`;
          if (fnArgs.path) return `${fnName}: ${this._shorten(fnArgs.path)}`;
          if (fnArgs.pattern) return `${fnName}: ${fnArgs.pattern}`;
        } catch {}
        return fnName;
      }

      const label = name.replace(/ToolCall$/, '').replace(/_/g, ' ');
      const detail = args.path || args.pattern || args.command || '';
      return detail ? `${label}: ${this._shorten(String(detail)).slice(0, 80)}` : label;
    },

    _describeToolDone(tc) {
      const { name, data } = this._extractTool(tc);
      const result = data.result || {};
      const success = result.success || {};
      const args = data.args || {};

      if (name === 'readToolCall' && success) {
        return { text: `Read ${this._shorten(args.path)} (${success.totalLines || '?'} lines)` };
      }
      if (name === 'writeToolCall' && success) {
        const p = this._shorten(success.path || args.path);
        return { text: `Wrote ${p} (${success.linesCreated || '?'} lines)` };
      }
      if (name === 'editToolCall' && success) {
        return { text: `Edited ${this._shorten(args.path)}` };
      }
      if (name === 'shellToolCall') {
        const exitCode = success.exitCode ?? success.exit_code;
        const stdout = (success.stdout || success.output || '').trim();
        const header = exitCode !== undefined ? `Shell completed (exit ${exitCode})` : 'Shell completed';
        return { text: header, output: stdout || null };
      }
      if (name === 'grepToolCall') return { text: 'Grep completed' };
      if (name === 'globToolCall') return { text: 'Glob completed' };
      if (name === 'updateTodosToolCall') return { text: 'Todos updated' };
      if (name === 'function') return { text: `${data.name || 'tool'} completed` };

      const label = name.replace(/ToolCall$/, '').replace(/_/g, ' ');
      return { text: `${label} completed` };
    },

    parseLogEvent(event) {
      switch (event.type) {
        case 'system':
          return [{ text: `--- Session started (${event.model || 'agent'}) ---`, cls: 'text-gray-500' }];

        case 'assistant': {
          const text = (event.message?.content || []).map(c => c.text || '').join('');
          if (!text.trim()) return null;
          return [{ text: text.trim(), cls: 'text-blue-300' }];
        }

        case 'tool_call': {
          const tc = event.tool_call || {};
          if (event.subtype === 'started') {
            return [{ text: `  \u25b6 ${this._describeToolStart(tc)}`, cls: 'text-yellow-400' }];
          }
          if (event.subtype === 'completed') {
            const info = this._describeToolDone(tc);
            const entries = [{ text: `  \u2714 ${info.text}`, cls: 'text-green-400' }];
            if (info.output) {
              const lines = info.output.split('\n');
              entries.push({
                type: 'output',
                lines,
                expanded: false,
                cls: 'text-gray-500',
              });
            }
            return entries;
          }
          return null;
        }

        case 'result':
          return [{ text: `--- Done (${((event.duration_ms || 0) / 1000).toFixed(1)}s) ---`, cls: 'text-gray-500' }];

        default:
          return null;
      }
    },

    copyLogs() {
      const text = this.logEntries.map(e => {
        if (e.type === 'output') return (e.lines || []).join('\n');
        return e.text || '';
      }).join('\n');
      navigator.clipboard.writeText(text);
      this.logsCopied = true;
      setTimeout(() => this.logsCopied = false, 2000);
    },

    async forceStopRun(runId) {
      if (!confirm('Force stop this run? The agent process will be killed.')) return;
      await API.post(`/api/runs/${runId}/stop`);
      this.stopLogStream();
      this.streamingRunId = null;
      this.runs = await API.get(`/api/tasks/${this.task.id}/runs`);
      await this.refreshTask(this.task.id);
    },

    async deleteRun(runId) {
      if (!confirm('Delete this run?')) return;
      await API.del(`/api/runs/${runId}`);
      if (this.expandedRun === runId) {
        this.expandedRun = null;
        this.stopLogStream();
        this.streamingRunId = null;
      }
      this.runs = await API.get(`/api/tasks/${this.task.id}/runs`);
    },

    async openRunModal() {
      const flows = Alpine.store('app').flows;
      this.runModalFlowSelect = '';
      this.runModalPrompt = '';
      this.runModalIsFirstRun = this.runs.length === 0;

      try {
        this.runModalAgents = await API.get('/api/agents');
        const project = this.task ? await API.get(`/api/projects/${this.task.project_id}`) : null;
        this.runModalProject = project;
        const da = (project?.aliases || {})['default'] || { agent: 'cursor', model: 'auto', flow_chain: ['default'] };
        this.runModalChain = [...(da.flow_chain || ['default'])];
        this.runModalAgent = this.runModalAgents.includes(da.agent) ? da.agent : (this.runModalAgents[0] || 'cursor');
        await this.loadRunModalModels(this.runModalAgent);
        this.runModalModel = da.model || this.runModalModels[0] || '';
      } catch (e) {
        this.runModalProject = null;
        this.runModalChain = [];
        this.runModalModel = '';
        this.runModalAgent = '';
      }

      this.runModal = true;
    },

    async loadRunModalModels(agent) {
      try {
        this.runModalModels = await API.get(`/api/models?agent=${encodeURIComponent(agent)}`);
        if (this.runModalModels.length && !this.runModalModels.includes(this.runModalModel)) {
          this.runModalModel = this.runModalModels[0];
        }
      } catch (e) {
        this.runModalModels = [];
      }
    },

    async onRunModalAgentChange(agent) {
      await this.loadRunModalModels(agent);
    },

    async submitRunModal() {
      if (!this.task || this.runModalChain.length === 0 || !this.runModalModel || !this.runModalAgent) return;
      await API.post(`/api/tasks/${this.task.id}/start`, {
        flow: this.runModalChain[0],
        flow_chain: this.runModalChain,
        user_prompt: this.runModalPrompt,
        model: this.runModalModel,
        agent: this.runModalAgent,
      });
      this.runModal = false;
      this.runs = await API.get(`/api/tasks/${this.task.id}/runs`);
    },

    sortedRunModalAliases() {
      const aliases = this.runModalProject?.aliases || {};
      const keys = Object.keys(aliases).sort((a, b) => (a === 'default' ? -1 : b === 'default' ? 1 : a.localeCompare(b)));
      return keys.map(k => ({ name: k, ...aliases[k] }));
    },

    applyRunModalAlias(name) {
      const cfg = (this.runModalProject?.aliases || {})[name];
      if (!cfg) return;
      if (cfg.agent && this.runModalAgents.includes(cfg.agent)) this.runModalAgent = cfg.agent;
      if (cfg.flow_chain) this.runModalChain = [...cfg.flow_chain];
      this.loadRunModalModels(this.runModalAgent).then(() => {
        if (cfg.model && this.runModalModels.includes(cfg.model)) this.runModalModel = cfg.model;
      });
    },

    back() {
      if (this.task) {
        Alpine.store('router').navigate('project', { projectId: this.task.project_id });
      } else {
        Alpine.store('router').navigate('dashboard');
      }
    },
  };
}
