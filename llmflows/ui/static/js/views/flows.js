/**
 * Flows list view.
 */
function flowsView() {
  return {
    flows: [],
    showCreate: false,
    newFlow: { name: '', description: '', copy_from: '' },

    async init() {
      await this.load();
    },

    async load() {
      this.flows = await API.get('/api/flows');
    },

    async createFlow() {
      const body = {
        name: this.newFlow.name,
        description: this.newFlow.description,
      };
      if (this.newFlow.copy_from) {
        body.copy_from = this.newFlow.copy_from;
      }
      try {
        await API.post('/api/flows', body);
        this.newFlow = { name: '', description: '', copy_from: '' };
        this.showCreate = false;
        await this.load();
        await Alpine.store('app').loadFlows();
      } catch (e) {
        alert('Error: ' + e.message);
      }
    },

    async deleteFlow(flowId) {
      if (!confirm('Delete this flow?')) return;
      try {
        await API.del(`/api/flows/${flowId}`);
        await this.load();
        await Alpine.store('app').loadFlows();
      } catch (e) {
        alert('Error: ' + e.message);
      }
    },

    async exportFlows() {
      const res = await fetch('/api/flows/export', { method: 'POST' });
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'flows.json';
      a.click();
      URL.revokeObjectURL(url);
    },

    async importFlows(event) {
      const file = event.target.files[0];
      if (!file) return;
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch('/api/flows/import', { method: 'POST', body: formData });
      if (res.ok) {
        const result = await res.json();
        alert(`Imported ${result.imported} flow(s)`);
        await this.load();
        await Alpine.store('app').loadFlows();
      } else {
        alert('Import failed');
      }
      event.target.value = '';
    },

    editFlow(flowId) {
      Alpine.store('router').navigate('flow-editor', { flowId });
    },
  };
}
