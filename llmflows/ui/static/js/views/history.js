/**
 * History view -- all runs across all projects, newest first.
 */
function historyView() {
  return {
    runs: [],
    total: 0,
    limit: 50,
    offset: 0,
    loading: false,
    expandedRun: null,
    streamingRunId: null,
    logEntries: [],
    logStreaming: false,
    _logEventSource: null,
    logsCopied: false,
    filterStatus: '',

    async init() {
      await this.load();
      this._interval = setInterval(() => this.load(), 5000);
    },

    destroy() {
      if (this._interval) clearInterval(this._interval);
      this.stopLogStream();
    },

    async load() {
      try {
        this.loading = this.runs.length === 0;
        const data = await API.get(`/api/history?limit=${this.limit}&offset=${this.offset}`);
        this.runs = data.runs;
        this.total = data.total;
      } catch (e) {
        console.error('History load error:', e);
      } finally {
        this.loading = false;
      }
    },

    filteredRuns() {
      if (!this.filterStatus) return this.runs;
      return this.runs.filter(r => {
        if (this.filterStatus === 'running') return r.status === 'running';
        if (this.filterStatus === 'queued') return r.status === 'queued';
        if (this.filterStatus === 'completed') return r.status === 'completed' && (!r.outcome || r.outcome === 'completed');
        if (this.filterStatus === 'failed') return r.status === 'completed' && r.outcome === 'failed';
        if (this.filterStatus === 'cancelled') return r.status === 'completed' && r.outcome === 'cancelled';
        if (this.filterStatus === 'timeout') return r.status === 'completed' && r.outcome === 'timeout';
        return true;
      });
    },

    get hasMore() {
      return this.offset + this.limit < this.total;
    },

    get hasPrev() {
      return this.offset > 0;
    },

    async nextPage() {
      if (!this.hasMore) return;
      this.offset += this.limit;
      await this.load();
    },

    async prevPage() {
      if (!this.hasPrev) return;
      this.offset = Math.max(0, this.offset - this.limit);
      await this.load();
    },

    get pageInfo() {
      const from = this.offset + 1;
      const to = Math.min(this.offset + this.limit, this.total);
      return `${from}\u2013${to} of ${this.total}`;
    },

    displayStatus(run) {
      if (run.status === 'completed' && run.outcome && run.outcome !== 'completed') {
        return run.outcome;
      }
      return run.status;
    },

    statusBadge(status) {
      return {
        queued: 'bg-blue-900/50 text-blue-300',
        running: 'bg-yellow-900/50 text-yellow-300',
        completed: 'bg-green-900/50 text-green-300',
        cancelled: 'bg-red-900/50 text-red-400',
        failed: 'bg-red-900/50 text-red-300',
        timeout: 'bg-orange-900/50 text-orange-300',
      }[status] || 'bg-gray-700 text-gray-300';
    },

    statusDot(run) {
      if (run.status === 'running') return 'bg-yellow-400 animate-pulse';
      if (run.status === 'queued') return 'bg-blue-400';
      if (run.status === 'completed') {
        if (run.outcome === 'failed') return 'bg-red-500';
        if (run.outcome === 'cancelled') return 'bg-red-400';
        if (run.outcome === 'timeout') return 'bg-orange-400';
        return 'bg-green-500';
      }
      return 'bg-gray-500';
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
      }
    },

    viewRunLogs(runId) {
      if (this.streamingRunId === runId) return;
      this.stopLogStream();
      this.streamingRunId = runId;
      this.logEntries = [];
      this.expandedRun = runId;

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
            const desc = this._describeToolStart(tc);
            return [{ text: `  \u25b6 ${desc}`, cls: 'text-yellow-400' }];
          }
          if (event.subtype === 'completed') {
            const info = this._describeToolDone(tc);
            const entries = [{ text: `  \u2714 ${info.text}`, cls: 'text-green-400' }];
            if (info.output) {
              entries.push({ type: 'output', lines: info.output.split('\n'), expanded: false, cls: 'text-gray-500' });
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
      if (name === 'readToolCall') return `Read ${args.path || '?'}`;
      if (name === 'writeToolCall') return `Write ${args.path || '?'}`;
      if (name === 'editToolCall') return `Edit ${args.path || '?'}`;
      if (name === 'shellToolCall') return `Shell: ${(args.command || '?').slice(0, 100)}`;
      if (name === 'grepToolCall') return `Grep: ${args.pattern || '?'}`;
      if (name === 'globToolCall') return `Glob: ${args.pattern || args.glob || '?'}`;
      if (name === 'function') {
        const fnName = data.name || 'tool';
        try {
          const fnArgs = JSON.parse(data.arguments || '{}');
          if (fnArgs.command) return `${fnName}: ${fnArgs.command.slice(0, 100)}`;
          if (fnArgs.path) return `${fnName}: ${fnArgs.path}`;
        } catch {}
        return fnName;
      }
      const label = name.replace(/ToolCall$/, '').replace(/_/g, ' ');
      const detail = args.path || args.pattern || args.command || '';
      return detail ? `${label}: ${String(detail).slice(0, 80)}` : label;
    },

    _describeToolDone(tc) {
      const { name, data } = this._extractTool(tc);
      const result = data.result || {};
      const success = result.success || {};
      const args = data.args || {};
      if (name === 'readToolCall' && success) return { text: `Read ${args.path} (${success.totalLines || '?'} lines)` };
      if (name === 'writeToolCall' && success) return { text: `Wrote ${success.path || args.path} (${success.linesCreated || '?'} lines)` };
      if (name === 'editToolCall' && success) return { text: `Edited ${args.path}` };
      if (name === 'shellToolCall') {
        const exitCode = success.exitCode ?? success.exit_code;
        const stdout = (success.stdout || success.output || '').trim();
        const header = exitCode !== undefined ? `Shell completed (exit ${exitCode})` : 'Shell completed';
        return { text: header, output: stdout || null };
      }
      if (name === 'grepToolCall') return { text: 'Grep completed' };
      if (name === 'globToolCall') return { text: 'Glob completed' };
      if (name === 'function') return { text: `${data.name || 'tool'} completed` };
      const label = name.replace(/ToolCall$/, '').replace(/_/g, ' ');
      return { text: `${label} completed` };
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

    goToTask(taskId) {
      Alpine.store('router').navigate('task', { taskId });
    },

    goToProject(run) {
      if (run.project_id) {
        Alpine.store('router').navigate('project', { projectId: run.project_id });
      }
    },
  };
}
