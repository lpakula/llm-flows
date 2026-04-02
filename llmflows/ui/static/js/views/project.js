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
    showAliasForm: false,
    showNewAliasForm: false,
    editingAlias: null,
    aliasForm: { name: '', agent: 'cursor', model: '', flow_chain: [], step_overrides: {} },
    aliasAddFlow: '',
    aliasFormModels: [],
    aliasFormSteps: [],
    aliasEditingStep: null,
    showSettingsForm: false,
    projectSettings: { is_git_repo: true },
    settingsSaving: false,

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
        [this.project, this.tasks, this.flows, this.agents, this.projectSettings] = await Promise.all([
          API.get(`/api/projects/${pid}`),
          API.get(`/api/projects/${pid}/tasks`),
          API.get('/api/flows'),
          API.get('/api/agents'),
          API.get(`/api/projects/${pid}/settings`),
        ]);
        const da = this._defaultAlias();
        await this.loadModelsForAgent(da.agent || 'cursor');
      } catch (e) {
        console.error('Project load error:', e);
      }
    },

    async loadModelsForAgent(agent) {
      try {
        this.models = await API.get(`/api/models?agent=${encodeURIComponent(agent)}`);
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
      this.aliasForm = { name: '', agent: defaultAgent, model: '', flow_chain: ['default'], step_overrides: {} };
      this.aliasAddFlow = '';
      this.aliasEditingStep = null;
      this.loadAliasFormModels(defaultAgent);
      this._loadAliasFormSteps();
    },

    async loadAliasFormModels(agent) {
      try {
        this.aliasFormModels = await API.get(`/api/models?agent=${encodeURIComponent(agent)}`);
        if (!this.aliasForm.model && this.aliasFormModels.length) {
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
        step_overrides: JSON.parse(JSON.stringify(cfg.step_overrides || {})),
      };
      this.aliasAddFlow = '';
      this.aliasEditingStep = null;
      await this.loadAliasFormModels(this.aliasForm.agent);
      if (cfg.model && this.aliasFormModels.includes(cfg.model)) {
        this.aliasForm.model = cfg.model;
      }
      this._loadAliasFormSteps();
    },

    async saveAlias() {
      if (!this.project || !this.aliasForm.name.trim()) return;
      const aliases = { ...(this.project.aliases || {}) };
      const cleanOverrides = {};
      for (const [k, v] of Object.entries(this.aliasForm.step_overrides || {})) {
        if (v.agent || v.model) cleanOverrides[k] = v;
      }
      const entry = {
        agent: this.aliasForm.agent,
        model: this.aliasForm.model,
        flow_chain: [...this.aliasForm.flow_chain],
      };
      if (Object.keys(cleanOverrides).length > 0) {
        entry.step_overrides = cleanOverrides;
      }
      aliases[this.aliasForm.name.trim()] = entry;
      await API.patch(`/api/projects/${this.project.id}`, { aliases });
      this.showNewAliasForm = false;
      this.resetAliasForm();
      await this.load(this.project.id);
    },

    _loadAliasFormSteps() {
      const steps = [];
      for (const flowName of (this.aliasForm.flow_chain || [])) {
        const flow = (this.flows || []).find(f => f.name === flowName);
        if (flow) {
          const sorted = [...(flow.steps || [])].sort((a, b) => a.position - b.position);
          for (const s of sorted) {
            steps.push({ flowName, stepName: s.name, key: `${flowName}/${s.name}` });
          }
        }
      }
      this.aliasFormSteps = steps;
    },

    getAliasStepOverride(key, field) {
      return (this.aliasForm.step_overrides[key] || {})[field] || '';
    },

    setAliasStepOverride(key, field, value) {
      if (!this.aliasForm.step_overrides[key]) {
        this.aliasForm.step_overrides[key] = {};
      }
      if (value) {
        this.aliasForm.step_overrides[key][field] = value;
      } else {
        delete this.aliasForm.step_overrides[key][field];
      }
      if (!this.aliasForm.step_overrides[key].agent && !this.aliasForm.step_overrides[key].model) {
        delete this.aliasForm.step_overrides[key];
      }
    },

    resolvedStepAgent(key) {
      return (this.aliasForm.step_overrides[key] || {}).agent || this.aliasForm.agent || 'cursor';
    },

    resolvedStepModel(key) {
      return (this.aliasForm.step_overrides[key] || {}).model || this.aliasForm.model || 'auto';
    },

    hasStepOverride(key) {
      const o = this.aliasForm.step_overrides[key];
      return o && (o.agent || o.model);
    },

    toggleStepEdit(key) {
      this.aliasEditingStep = this.aliasEditingStep === key ? null : key;
    },

    removeFlowFromChain(index) {
      this.aliasForm.flow_chain.splice(index, 1);
      this._loadAliasFormSteps();
      this.aliasEditingStep = null;
    },

    addFlowToChain() {
      if (!this.aliasAddFlow) return;
      this.aliasForm.flow_chain.push(this.aliasAddFlow);
      this.aliasAddFlow = '';
      this._loadAliasFormSteps();
    },

    async deleteAlias(name) {
      if (!this.project || name === 'default') return;
      const aliases = { ...(this.project.aliases || {}) };
      delete aliases[name];
      await API.patch(`/api/projects/${this.project.id}`, { aliases });
      await this.load(this.project.id);
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

    toggleSettingsForm() {
      this.showSettingsForm = !this.showSettingsForm;
    },

    async toggleGitRepo() {
      this.projectSettings.is_git_repo = !this.projectSettings.is_git_repo;
      await this.saveProjectSettings();
    },

    async saveProjectSettings() {
      if (!this.project) return;
      this.settingsSaving = true;
      try {
        this.projectSettings = await API.patch(
          `/api/projects/${this.project.id}/settings`,
          { is_git_repo: this.projectSettings.is_git_repo },
        );
      } catch (e) {
        console.error('Failed to save settings:', e);
      }
      this.settingsSaving = false;
    },
  };
}
