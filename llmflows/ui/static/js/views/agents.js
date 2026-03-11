/**
 * Agents view -- tile cards for each agent backend with status detection.
 */
function agentsView() {
  return {
    agents: {},
    loading: true,

    async init() {
      try {
        this.agents = await API.get('/api/agents/status');
      } catch (e) {
        this.agents = {};
      }
      this.loading = false;
    },

    get agentList() {
      return Object.entries(this.agents).map(([key, info]) => ({ key, ...info }));
    },
  };
}
