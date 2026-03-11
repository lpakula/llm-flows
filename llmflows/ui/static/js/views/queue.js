/**
 * Queue landing page view.
 */
function queueView() {
  return {
    queue: [],

    async init() {
      await this.refresh();
      this._interval = setInterval(() => this.refresh(), 5000);
    },

    destroy() {
      if (this._interval) clearInterval(this._interval);
    },

    async refresh() {
      try {
        this.queue = await API.get('/api/queue');
      } catch (e) {
        console.error('Queue load error:', e);
      }
    },
  };
}
