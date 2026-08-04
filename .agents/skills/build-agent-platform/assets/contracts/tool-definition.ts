import type { AgentDefinition } from "./agent-definition.js";

export interface RequestContext {
  requestId: string;
  userId?: string;
}

export interface SessionContext {
  sessionId: string;
}

export interface AgentRegistry {
  get(agentId: string): AgentDefinition | undefined;
}

export interface ToolResult<TOutput> {
  output: TOutput;
}

export interface AgentTool<TInput, TOutput> {
  execute(input: TInput, signal: AbortSignal): Promise<ToolResult<TOutput>>;
}

/** The request-scoped dependencies available while constructing a tool. */
export interface ToolContext {
  request: RequestContext;
  session: SessionContext;
  agents: AgentRegistry;
  signal: AbortSignal;
  services: ReadonlyMap<string, unknown>;
}

/** A registered tool factory with a stable, agent-facing input contract. */
export interface ToolDefinition<TInput, TOutput> {
  name: string;
  description: string;
  inputSchema: unknown;
  create(context: ToolContext): AgentTool<TInput, TOutput>;
}
