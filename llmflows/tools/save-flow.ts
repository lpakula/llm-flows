/**
 * Pi extension: save_flow tool.
 *
 * Creates a flow directly in the llmflows database by calling the
 * running llmflows REST API.  The flow (and its steps) appear
 * immediately in the UI — no manual import needed.
 *
 * Environment variables (set by the chat endpoint):
 *   LLMFLOWS_API_BASE        – e.g. "http://localhost:4301"
 *   LLMFLOWS_CHAT_SPACE_ID   – target space ID
 */

import { Type } from "@sinclair/typebox";

const API_BASE = process.env.LLMFLOWS_API_BASE || "http://localhost:4301";
const SPACE_ID = process.env.LLMFLOWS_CHAT_SPACE_ID || "";

const GateSchema = Type.Object({
  command: Type.String({ description: "Shell command that must exit 0" }),
  message: Type.String({ description: "Human-readable failure description" }),
});

const StepSchema = Type.Object({
  name: Type.String({ description: "Step name" }),
  position: Type.Number({ description: "0-indexed position in the flow" }),
  content: Type.String({
    description:
      "Markdown prompt for the step. Use # TITLE, ## PURPOSE, ## WORKFLOW, ## RULES sections.",
  }),
  step_type: Type.String({
    description:
      '"agent" for AI-powered steps (research, analysis, writing, automation), ' +
      '"code" for steps that edit source code in a software project, ' +
      '"hitl" for human-in-the-loop review.',
  }),
  agent_alias: Type.Optional(
    Type.String({ description: '"mini", "normal", or "max". Omit for normal.' }),
  ),
  gates: Type.Optional(Type.Array(GateSchema)),
  ifs: Type.Optional(Type.Array(GateSchema)),
  allow_max: Type.Optional(Type.Boolean()),
  max_gate_retries: Type.Optional(Type.Number()),
  skills: Type.Optional(Type.Array(Type.String())),
});

export default function activate(api: any) {
  api.registerTool({
    name: "save_flow",
    label: "Save Flow",
    description:
      "Create a new flow with steps in the current llm-flows space. " +
      "The flow appears immediately in the UI. " +
      "Use this when the user asks you to build or create a flow.",
    promptSnippet:
      "save_flow: Create a flow in llm-flows. " +
      "Params: name, description, " +
      "steps (array of {name, position, content, step_type ('agent'|'code'|'hitl'), " +
      "agent_alias?, gates?, ifs?, allow_max?, max_gate_retries?, skills?}), " +
      "requirements? ({tools?, variables?}).",
    parameters: Type.Object({
      name: Type.String({
        description: "Flow name (lowercase, hyphenated, e.g. 'crypto-news')",
      }),
      description: Type.String({ description: "Brief description of what the flow does" }),
      steps: Type.Array(StepSchema, { description: "Ordered list of flow steps" }),
      requirements: Type.Optional(
        Type.Object({
          tools: Type.Optional(
            Type.Array(Type.String(), { description: 'e.g. ["web_search"]' }),
          ),
          variables: Type.Optional(
            Type.Array(Type.String(), { description: 'e.g. ["API_KEY"]' }),
          ),
        }),
      ),
    }),

    async execute(
      _toolCallId: string,
      params: {
        name: string;
        description: string;
        steps: Array<Record<string, unknown>>;
        requirements?: { tools?: string[]; variables?: string[] };
      },
    ) {
      if (!SPACE_ID) {
        return {
          content: [
            {
              type: "text",
              text: "Error: No space is selected. Ask the user to select a space in the sidebar before creating a flow.",
            },
          ],
        };
      }

      // 1. Create the flow
      const flowRes = await fetch(`${API_BASE}/api/spaces/${SPACE_ID}/flows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: params.name, description: params.description }),
      });

      if (!flowRes.ok) {
        const err = await flowRes.text();
        return { content: [{ type: "text", text: `Error creating flow: ${err}` }] };
      }

      const flow = (await flowRes.json()) as { id: string };

      // 2. Set requirements if provided
      if (params.requirements) {
        const reqRes = await fetch(`${API_BASE}/api/flows/${flow.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ requirements: params.requirements }),
        });
        if (!reqRes.ok) {
          const err = await reqRes.text();
          return {
            content: [{ type: "text", text: `Flow created but failed to set requirements: ${err}` }],
          };
        }
      }

      // 3. Add steps
      for (const step of params.steps) {
        const stepRes = await fetch(`${API_BASE}/api/flows/${flow.id}/steps`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(step),
        });
        if (!stepRes.ok) {
          const err = await stepRes.text();
          return {
            content: [
              {
                type: "text",
                text: `Flow "${params.name}" created but failed adding step "${step.name}": ${err}`,
              },
            ],
          };
        }
      }

      return {
        content: [
          {
            type: "text",
            text:
              `Flow "${params.name}" created successfully with ${params.steps.length} step(s). ` +
              `It is now visible in the Flows section of the UI.`,
          },
        ],
      };
    },
  });
}
