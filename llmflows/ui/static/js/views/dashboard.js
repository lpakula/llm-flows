/**
 * Dashboard view logic.
 */
function dashboardView() {
  return {
    loading: true,
    data: null,

    async init() {
      await this.refresh();
      this._interval = setInterval(() => this.refresh(), 8000);
    },

    destroy() {
      if (this._interval) clearInterval(this._interval);
    },

    async refresh() {
      try {
        this.data = await API.get('/api/dashboard');
      } catch (e) {
        console.error('Dashboard load error:', e);
      }
      this.loading = false;
    },

    totalTasks(entry) {
      return Object.values(entry.task_counts || {}).reduce((a, b) => a + b, 0);
    },

    statusBadge(status) {
      const colors = {
        idle: 'bg-gray-700 text-gray-300',
        queued: 'bg-blue-900/50 text-blue-300',
        running: 'bg-yellow-900/50 text-yellow-300',
      };
      return colors[status] || 'bg-gray-700 text-gray-300';
    },
  };
}
