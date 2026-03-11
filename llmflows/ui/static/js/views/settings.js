/**
 * Settings view -- daemon configuration.
 */
function settingsView() {
  return {
    pollInterval: 30,
    runTimeout: 60,
    gateTimeout: 60,
    loading: true,
    saving: false,
    saved: false,

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        const config = await API.get('/api/config/daemon');
        this.pollInterval = config.poll_interval_seconds ?? 30;
        this.runTimeout = config.run_timeout_minutes ?? 60;
        this.gateTimeout = config.gate_timeout_seconds ?? 60;
      } catch (e) {
        console.error('Failed to load daemon config:', e);
      }
      this.loading = false;
    },

    async save() {
      this.saving = true;
      try {
        const updated = await API.patch('/api/config/daemon', {
          poll_interval_seconds: this.pollInterval,
          run_timeout_minutes: this.runTimeout,
          gate_timeout_seconds: this.gateTimeout,
        });
        this.pollInterval = updated.poll_interval_seconds;
        this.runTimeout = updated.run_timeout_minutes;
        this.gateTimeout = updated.gate_timeout_seconds;
        this.saved = true;
        setTimeout(() => this.saved = false, 3000);
      } catch (e) {
        console.error('Failed to save daemon config:', e);
      }
      this.saving = false;
    },
  };
}
