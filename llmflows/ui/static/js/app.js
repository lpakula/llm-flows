/**
 * llmflows UI -- Alpine.js stores, client-side router, API helpers.
 */

const API = {
  async get(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`GET ${url}: ${res.status}`);
    return res.json();
  },
  async post(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`POST ${url}: ${res.status}`);
    return res.json();
  },
  async patch(url, body) {
    const res = await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`PATCH ${url}: ${res.status}`);
    return res.json();
  },
  async del(url) {
    const res = await fetch(url, { method: 'DELETE' });
    if (!res.ok) throw new Error(`DELETE ${url}: ${res.status}`);
    return res.json();
  },
};

document.addEventListener('alpine:init', () => {
  Alpine.store('router', {
    view: 'dashboard',
    params: {},

    navigate(view, params = {}) {
      this.view = view;
      this.params = params;
      this._pushHash();
    },

    _pushHash() {
      const parts = [this.view];
      if (this.view === 'project' && this.params.projectId) parts.push(this.params.projectId);
      if (this.view === 'task' && this.params.taskId) parts.push(this.params.taskId);
      if (this.view === 'flow-editor' && this.params.flowId) parts.push(this.params.flowId);
      const hash = '#/' + parts.join('/');
      if (location.hash !== hash) history.pushState(null, '', hash);
    },

    _restoreFromHash() {
      const hash = (location.hash || '').replace(/^#\/?/, '');
      if (!hash) { this.view = 'dashboard'; this.params = {}; return; }
      const [view, id] = hash.split('/');
      const paramMap = {
        project: 'projectId',
        task: 'taskId',
        'flow-editor': 'flowId',
      };
      this.view = view || 'dashboard';
      this.params = id && paramMap[view] ? { [paramMap[view]]: id } : {};
    },
  });

  window.addEventListener('popstate', () => {
    Alpine.store('router')._restoreFromHash();
  });

  Alpine.store('app', {
    projects: [],
    flows: [],
    dashboard: null,

    async loadProjects() {
      this.projects = await API.get('/api/projects');
    },
    async loadFlows() {
      this.flows = await API.get('/api/flows');
    },
    async loadDashboard() {
      this.dashboard = await API.get('/api/dashboard');
    },
    async init() {
      await Promise.all([this.loadProjects(), this.loadFlows(), this.loadDashboard()]);
      Alpine.store('router')._restoreFromHash();
    },
  });
});

window.API = API;
