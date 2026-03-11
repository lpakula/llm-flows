/**
 * Project view -- task list + queue panel.
 */
function projectView() {
  return {
    project: null,
    tasks: [],
    flows: [],
    models: [],
    agents: [],
    showCreate: false,
    editingName: false,
    editName: '',
    newTask: { title: '', description: '', type: 'feature' },
    startingTask: null,
    startChain: ['default'],
    addFlowSelect: '',
    startPrompt: '',
    startModel: '',
    startAgent: '',
    isFirstRun: false,
    showAliasForm: false,
    showNewAliasForm: false,
    editingAlias: null,
    aliasForm: { name: '', agent: 'cursor', model: '', flow_chain: [] },
    aliasAddFlow: '',
    aliasFormModels: [],

    async init() {
      const pid = Alpine.store('router').params.projectId;
      if (!pid) return;
      await this.load(pid);
      this._interval = setInterval(() => this.load(pid), 5000);
    },

    destroy() {
      if (this._interval) clearInterval(this._interval);
    },

    _defaultAlias() {
      return (this.project?.aliases || {})['default'] || { agent: 'cursor', model: 'auto', flow_chain: ['default'] };
    },

    sortedAliases() {
      const aliases = this.project?.aliases || {};
      const keys = Object.keys(aliases).sort((a, b) => (a === 'default' ? -1 : b === 'default' ? 1 : a.localeCompare(b)));
      return keys.map(k => ({ name: k, ...aliases[k] }));
    },

    async load(pid) {
      try {
        [this.project, this.tasks, this.flows, this.agents] = await Promise.all([
          API.get(`/api/projects/${pid}`),
          API.get(`/api/projects/${pid}/tasks`),
          API.get('/api/flows'),
          API.get('/api/agents'),
        ]);
        const da = this._defaultAlias();
        await this.loadModelsForAgent(this.startAgent || da.agent || 'cursor');
      } catch (e) {
        console.error('Project load error:', e);
      }
    },

    async loadModelsForAgent(agent) {
      try {
        this.models = await API.get(`/api/models?agent=${encodeURIComponent(agent)}`);
        if (this.models.length && !this.models.includes(this.startModel)) {
          this.startModel = this.models[0];
        }
      } catch (e) {
        this.models = [];
      }
    },

    statusColor(status) {
      return {
        backlog: 'bg-gray-600', pending: 'bg-blue-500',
        executing: 'bg-yellow-500', completed: 'bg-green-500',
      }[status] || 'bg-gray-600';
    },

    statusBadge(status) {
      return {
        idle: 'bg-gray-700 text-gray-300',
        queued: 'bg-blue-900/50 text-blue-300',
        running: 'bg-yellow-900/50 text-yellow-300',
      }[status] || 'bg-gray-700 text-gray-300';
    },

    typeColor(type) {
      return {
        feature: 'text-blue-400', fix: 'text-red-400',
        refactor: 'text-yellow-400', chore: 'text-gray-400',
      }[type] || 'text-gray-400';
    },

    async createTask() {
      const pid = this.project?.id;
      if (!pid) return;
      await API.post(`/api/projects/${pid}/tasks`, this.newTask);
      this.newTask = { title: '', description: '', type: 'feature' };
      this.showCreate = false;
      await this.load(pid);
    },

    async renameProject() {
      if (!this.editName.trim() || !this.project) return;
      await API.patch(`/api/projects/${this.project.id}`, { name: this.editName.trim() });
      this.editingName = false;
      await this.load(this.project.id);
      Alpine.store('app').init();
    },

    async deleteProject() {
      if (!this.project) return;
      if (!confirm(`Delete project "${this.project.name}"? All tasks and runs will be lost.`)) return;
      await API.del(`/api/projects/${this.project.id}`);
      Alpine.store('app').init();
      Alpine.store('router').navigate('dashboard');
    },

    async openStartDialog(task) {
      const da = this._defaultAlias();
      this.startingTask = task.id;
      this.startChain = [...(da.flow_chain || ['default'])];
      this.addFlowSelect = '';
      this.startPrompt = '';
      this.startAgent = this.agents.includes(da.agent) ? da.agent : (this.agents[0] || 'cursor');
      await this.loadModelsForAgent(this.startAgent);
      this.startModel = da.model || this.models[0] || '';
      this.isFirstRun = (task.run_count || 0) === 0;
    },

    async onAgentChange(agent) {
      await this.loadModelsForAgent(agent);
    },

    async confirmStart() {
      if (!this.startingTask || this.startChain.length === 0 || !this.startModel || !this.startAgent) return;
      await API.post(`/api/tasks/${this.startingTask}/start`, {
        flow: this.startChain[0],
        flow_chain: this.startChain,
        user_prompt: this.startPrompt,
        model: this.startModel,
        agent: this.startAgent,
      });
      this.startingTask = null;
      await this.load(this.project.id);
    },

    // -- Alias management --

    toggleAliasPanel() {
      this.showAliasForm = !this.showAliasForm;
      if (this.showAliasForm) {
        this.showNewAliasForm = false;
        this.resetAliasForm();
      }
    },

    resetAliasForm() {
      this.editingAlias = null;
      const defaultAgent = this.agents[0] || 'cursor';
      this.aliasForm = { name: '', agent: defaultAgent, model: '', flow_chain: ['default'] };
      this.aliasAddFlow = '';
      this.loadAliasFormModels(defaultAgent);
    },

    async loadAliasFormModels(agent) {
      try {
        this.aliasFormModels = await API.get(`/api/models?agent=${encodeURIComponent(agent)}`);
        if (this.aliasFormModels.length && !this.aliasFormModels.includes(this.aliasForm.model)) {
          this.aliasForm.model = this.aliasFormModels[0];
        }
      } catch (e) {
        this.aliasFormModels = [];
      }
    },

    async editAlias(name) {
      const cfg = (this.project?.aliases || {})[name];
      if (!cfg) return;
      this.editingAlias = name;
      this.aliasForm = {
        name,
        agent: cfg.agent || this.agents[0] || 'cursor',
        model: cfg.model || '',
        flow_chain: [...(cfg.flow_chain || ['default'])],
      };
      this.aliasAddFlow = '';
      await this.loadAliasFormModels(this.aliasForm.agent);
      if (cfg.model && this.aliasFormModels.includes(cfg.model)) {
        this.aliasForm.model = cfg.model;
      }
    },

    async saveAlias() {
      if (!this.project || !this.aliasForm.name.trim()) return;
      const aliases = { ...(this.project.aliases || {}) };
      aliases[this.aliasForm.name.trim()] = {
        agent: this.aliasForm.agent,
        model: this.aliasForm.model,
        flow_chain: [...this.aliasForm.flow_chain],
      };
      await API.patch(`/api/projects/${this.project.id}`, { aliases });
      this.showNewAliasForm = false;
      this.resetAliasForm();
      await this.load(this.project.id);
    },

    async deleteAlias(name) {
      if (!this.project || name === 'default') return;
      const aliases = { ...(this.project.aliases || {}) };
      delete aliases[name];
      await API.patch(`/api/projects/${this.project.id}`, { aliases });
      await this.load(this.project.id);
    },

    applyAlias(name) {
      const cfg = (this.project?.aliases || {})[name];
      if (!cfg) return;
      if (cfg.agent && this.agents.includes(cfg.agent)) this.startAgent = cfg.agent;
      if (cfg.flow_chain) this.startChain = [...cfg.flow_chain];
      this.loadModelsForAgent(this.startAgent).then(() => {
        if (cfg.model && this.models.includes(cfg.model)) this.startModel = cfg.model;
      });
    },

    async deleteTask(taskId) {
      if (!confirm('Delete this task?')) return;
      await API.del(`/api/tasks/${taskId}`);
      await this.load(this.project.id);
    },

    openTask(taskId) {
      Alpine.store('router').navigate('task', { taskId });
    },

    sortedTasks() {
      return [...this.tasks].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    },
  };
}
