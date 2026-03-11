/**
 * Integrations view -- GitHub token + per-project enable/disable.
 */
function integrationsView() {
  return {
    token: '',
    maskedToken: '',
    hasToken: false,
    tokenSaved: false,
    projects: [],
    integrations: {},
    loading: true,

    async init() {
      await this.load();
      this._interval = setInterval(() => this.loadProjects(), 15000);
    },

    destroy() {
      if (this._interval) clearInterval(this._interval);
    },

    async load() {
      this.loading = true;
      await Promise.all([this.loadToken(), this.loadProjects()]);
      this.loading = false;
    },

    async loadToken() {
      try {
        const data = await API.get('/api/config/github');
        this.hasToken = data.has_token;
        this.maskedToken = data.masked_token || '';
      } catch (e) {}
    },

    async saveToken() {
      try {
        await API.patch('/api/config/github', { token: this.token });
        this.tokenSaved = true;
        this.token = '';
        await this.loadToken();
        setTimeout(() => this.tokenSaved = false, 3000);
      } catch (e) {
        console.error('Failed to save token:', e);
      }
    },

    async loadProjects() {
      try {
        this.projects = await API.get('/api/projects');
        for (const p of this.projects) {
          const intgs = await API.get(`/api/projects/${p.id}/integrations`);
          this.integrations[p.id] = intgs.find(i => i.provider === 'github') || null;
        }
      } catch (e) {}
    },

    getIntegration(projectId) {
      return this.integrations[projectId] || null;
    },

    isEnabled(projectId) {
      const intg = this.getIntegration(projectId);
      return intg ? intg.enabled : false;
    },

    getRepo(projectId) {
      const intg = this.getIntegration(projectId);
      return intg ? (intg.config?.repo || '') : '';
    },

    getLastPolled(projectId) {
      const intg = this.getIntegration(projectId);
      if (!intg || !intg.last_polled_at) return 'Never';
      return new Date(intg.last_polled_at).toLocaleString();
    },

    async toggleEnabled(projectId) {
      const intg = this.getIntegration(projectId);
      if (intg) {
        await API.patch(`/api/integrations/${intg.id}`, { enabled: !intg.enabled });
      } else {
        await API.post(`/api/projects/${projectId}/integrations`, {
          provider: 'github',
          config: {},
        });
      }
      await this.loadProjects();
    },

    async detectRepo(projectId) {
      const intg = this.getIntegration(projectId);
      if (!intg) {
        await API.post(`/api/projects/${projectId}/integrations`, {
          provider: 'github',
          config: {},
        });
        await this.loadProjects();
      }
      const current = this.getIntegration(projectId);
      if (!current) return;
      try {
        await API.post(`/api/integrations/${current.id}/detect-repo`);
        await this.loadProjects();
      } catch (e) {
        console.error('Failed to detect repo:', e);
      }
    },
  };
}
