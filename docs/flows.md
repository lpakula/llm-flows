# Flow Authoring

Flows are fully customizable. You can define step order, step instructions, gate commands, and project-specific validation logic.

A good flow is usually a small number of clear steps, with fast and reliable gates, instructions specific enough to guide the agent, and strict enough to block bad output without making progress impossible.

## 🎓 Recommended first flow

For new users, start with a simple 3-step workflow:

1. **Understand** — inspect the task and relevant files
2. **Implement** — make the change
3. **Validate** — run tests, build, or lint

This keeps the protocol easy to understand while showing the value of enforced gates.

---

## 🧩 Example flow step

A flow step defines what the agent should do and what must pass before advancing:

```json
{
  "name": "validate",
  "content": "# TEST\n\nStart the dev server and verify it compiles without errors.",
  "gates": [
    {
      "command": "npm run build",
      "message": "Build failed. Fix all compilation errors before advancing."
    }
  ]
}
```