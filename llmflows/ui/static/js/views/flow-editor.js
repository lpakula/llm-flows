/**
 * Flow editor view -- steps, reorder.
 */
function flowEditorView() {
  return {
    flow: null,
    editingMeta: false,
    metaForm: { name: '', description: '' },
    editingStep: null,
    stepForm: { name: '', content: '', gates: [] },
    showAddStep: false,
    newStep: { name: '', content: '', position: null, gates: [] },
    _sortable: null,

    async init() {
      const fid = Alpine.store('router').params.flowId;
      if (!fid) return;
      await this.load(fid);
    },

    destroy() {
      if (this._sortable) this._sortable.destroy();
    },

    async load(fid) {
      this.flow = await API.get(`/api/flows/${fid}`);
      this.metaForm = { name: this.flow.name, description: this.flow.description || '' };
      this.$nextTick(() => this.initSortable());
    },

    initSortable() {
      const el = this.$refs?.stepList;
      if (!el) return;
      if (this._sortable) this._sortable.destroy();
      this._sortable = new Sortable(el, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        handle: '.drag-handle',
        onEnd: async () => {
          const stepIds = Array.from(el.children).map(c => c.dataset.stepId).filter(Boolean);
          const stepMap = Object.fromEntries(this.flow.steps.map(s => [s.id, s]));
          const fid = this.flow.id;
          const reordered = stepIds.map(id => stepMap[id]).filter(Boolean);
          // Destroy Sortable so it no longer owns the DOM nodes.
          if (this._sortable) { this._sortable.destroy(); this._sortable = null; }
          // Null out flow so Alpine tears down the x-for entirely (no keyed-reconcile
          // confusion from Sortable's moved nodes), then restore with correct order.
          const flowMeta = { id: this.flow.id, name: this.flow.name,
                             description: this.flow.description };
          this.flow = null;
          await this.$nextTick();
          this.flow = { ...flowMeta, steps: reordered };
          await API.post(`/api/flows/${fid}/reorder`, { step_ids: stepIds });
          // Full reload from DB to confirm, re-inits Sortable.
          await this.load(fid);
        },
      });
    },

    async saveMeta() {
      await API.patch(`/api/flows/${this.flow.id}`, {
        name: this.metaForm.name,
        description: this.metaForm.description,
      });
      this.editingMeta = false;
      await this.load(this.flow.id);
      await Alpine.store('app').loadFlows();
    },

    startEditStep(step) {
      this.editingStep = step.id;
      const gates = (step.gates || []).map(g => ({ ...g }));
      this.stepForm = { name: step.name, content: step.content || '', gates };
    },

    cancelEditStep() {
      this.editingStep = null;
      this.stepForm = { name: '', content: '', gates: [] };
    },

    addGate(form) {
      form.gates.push({ command: '', message: '' });
    },

    removeGate(form, index) {
      form.gates.splice(index, 1);
    },

    async saveStep(stepId) {
      const gates = this.stepForm.gates.filter(g => g.command.trim());
      await API.patch(`/api/flows/${this.flow.id}/steps/${stepId}`, {
        name: this.stepForm.name,
        content: this.stepForm.content,
        gates,
      });
      this.editingStep = null;
      await this.load(this.flow.id);
    },

    async addStep() {
      const gates = this.newStep.gates.filter(g => g.command.trim());
      const body = { name: this.newStep.name, content: this.newStep.content };
      if (gates.length) body.gates = gates;
      if (this.newStep.position !== null && this.newStep.position !== '') {
        body.position = parseInt(this.newStep.position);
      }
      await API.post(`/api/flows/${this.flow.id}/steps`, body);
      this.newStep = { name: '', content: '', position: null, gates: [] };
      this.showAddStep = false;
      await this.load(this.flow.id);
    },

    async removeStep(stepId) {
      if (!confirm('Remove this step?')) return;
      await API.del(`/api/flows/${this.flow.id}/steps/${stepId}`);
      await this.load(this.flow.id);
    },

    async duplicateFlow() {
      const newName = prompt('Name for the copy:', this.flow.name + '-copy');
      if (!newName) return;
      try {
        const created = await API.post('/api/flows', {
          name: newName,
          copy_from: this.flow.name,
        });
        await Alpine.store('app').loadFlows();
        Alpine.store('router').navigate('flow-editor', { flowId: created.id });
      } catch (e) {
        alert('Error: ' + e.message);
      }
    },

    back() {
      Alpine.store('router').navigate('flows');
    },
  };
}
