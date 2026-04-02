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
    logAtBottom: true,
    runSteps: {},
    editingDescription: false,
    editDescText: '',

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
            this.loadRunSteps(activeRun.id);
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
            if (this.expandedRun) this.loadRunSteps(this.expandedRun);
            break;
          }
        }
      } catch (e) {}
    },

    async loadRunSteps(runId) {
      try {
        const data = await API.get(`/api/runs/${runId}/steps`);
        this.runSteps[runId] = data.steps || [];
      } catch (e) {
        this.runSteps[runId] = [];
      }
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
        interrupted: 'bg-red-900/50 text-red-300',
        error: 'bg-red-900/50 text-red-300',
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

    duration(run) {
      if (!run.started_at) return '-';
      const start = new Date(run.started_at);
      const end = run.completed_at ? new Date(run.completed_at) : new Date();
      const ms = end - start;
      if (ms < 1000) return '<1s';
      const s = Math.floor(ms / 1000);
      if (s < 60) return s + 's';
      const m = Math.floor(s / 60);
      const rs = s % 60;
      if (m < 60) return m + 'm ' + rs + 's';
      const h = Math.floor(m / 60);
      return h + 'h ' + (m % 60) + 'm';
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
        this.loadRunSteps(runId);
        const run = this.runs.find(r => r.id === runId);
        if (run && this.isRunActive(run)) {
          this.viewRunLogs(runId);
        }
      }
    },

    _scrollLogIfAtBottom() {
      if (this.logAtBottom && this.$refs.logScroll) {
        this.$nextTick(() => {
          const el = this.$refs.logScroll;
          if (el) el.scrollTop = el.scrollHeight;
        });
      }
    },

    viewRunLogs(runId) {
      if (this.streamingRunId === runId) return;
      this.stopLogStream();
      this.streamingRunId = runId;
      this.logEntries = [];
      this.logAtBottom = true;

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
            this._scrollLogIfAtBottom();
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

    _describeClaudeToolUse(c) {
      const name = c.name || 'tool';
      const input = c.input || {};
      if (input.command) return `${name}: ${input.command.slice(0, 100)}`;
      if (input.file_path || input.path) return `${name}: ${this._shorten(input.file_path || input.path)}`;
      if (input.pattern) return `${name}: ${input.pattern}`;
      if (input.glob_pattern) return `${name}: ${input.glob_pattern}`;
      return name;
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
          const parts = (event.message?.content || []).filter(c => c.type !== 'thinking');
          const entries = [];
          for (const c of parts) {
            if (c.type === 'text' && c.text?.trim()) {
              entries.push({ text: c.text.trim(), cls: 'text-blue-300' });
            } else if (c.type === 'tool_use') {
              const label = this._describeClaudeToolUse(c);
              entries.push({ text: `  \u25b6 ${label}`, cls: 'text-yellow-400' });
            }
          }
          return entries.length ? entries : null;
        }

        case 'user': {
          const parts = (event.message?.content || []);
          const entries = [];
          for (const c of parts) {
            if (c.type !== 'tool_result') continue;
            const stdout = (event.tool_use_result?.stdout || c.content || '').trim();
            const isErr = c.is_error || false;
            const header = isErr ? 'Tool error' : 'Tool completed';
            entries.push({ text: `  \u2714 ${header}`, cls: isErr ? 'text-red-400' : 'text-green-400' });
            if (stdout) {
              entries.push({ type: 'output', lines: stdout.split('\n'), expanded: false, cls: 'text-gray-500' });
            }
          }
          return entries.length ? entries : null;
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

        case 'thinking':
          return null;

        case 'raw':
          return event.text ? [{ text: event.text, cls: 'text-red-400' }] : null;

        default: {
          const msg = event.message || event.error || event.text || event.data || JSON.stringify(event);
          const text = typeof msg === 'string' ? msg : JSON.stringify(msg);
          if (!text.trim() || text === '{}') return null;
          const cls = (event.type === 'error' || text.toLowerCase().includes('error') || text.toLowerCase().includes('cannot'))
            ? 'text-red-400' : 'text-gray-400';
          return [{ text: text.trim(), cls }];
        }
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
        if (!this.runModalModel && this.runModalModels.length) {
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
      let prompt = this.runModalPrompt;
      if (this.runModalIsFirstRun && this.runModalPrompt.trim()) {
        const desc = (this.task.description || '').trim();
        prompt = desc ? desc + '\n\n' + this.runModalPrompt.trim() : this.runModalPrompt.trim();
      }
      await API.post(`/api/tasks/${this.task.id}/start`, {
        flow: this.runModalChain[0],
        flow_chain: this.runModalChain,
        user_prompt: prompt,
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
        if (cfg.model) this.runModalModel = cfg.model;
      });
    },

    stepBoxClass(status) {
      return {
        completed: 'bg-green-900/40 border-green-700 text-green-400',
        current: 'bg-yellow-900/40 border-yellow-600 text-yellow-300 font-semibold',
        skipped: 'bg-gray-900/30 border-gray-800 text-gray-600',
        pending: 'bg-gray-900/50 border-gray-700 text-gray-500',
      }[status] || 'bg-gray-900/50 border-gray-700 text-gray-500';
    },

    stepConnectorClass(status) {
      return {
        completed: 'bg-green-700',
        current: 'bg-yellow-600',
        skipped: 'bg-gray-800',
        pending: 'bg-gray-800',
      }[status] || 'bg-gray-800';
    },

    startEditDescription() {
      this.editDescText = this.task?.description || '';
      this.editingDescription = true;
    },

    async saveDescription() {
      if (!this.task) return;
      try {
        this.task = await API.patch(`/api/tasks/${this.task.id}`, { description: this.editDescText });
        this.editingDescription = false;
      } catch (e) {
        console.error('Failed to save description:', e);
      }
    },

    cancelEditDescription() {
      this.editingDescription = false;
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
