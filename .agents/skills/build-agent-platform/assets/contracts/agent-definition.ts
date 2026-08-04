/** A system prompt supplied inline or loaded from a stable source path. */
export interface PromptSource {
  kind: "inline" | "file";
  value: string;
}

/** Model selection and an optional deterministic fallback. */
export interface ModelPolicy {
  provider: string;
  model: string;
  thinkingLevel?: "off" | "low" | "medium" | "high";
  fallback?: {
    provider: string;
    model: string;
  };
}

/** Controls which discovered skills an agent may load. */
export interface SkillSelectionPolicy {
  allow: string[];
  allowImplicitMatch?: boolean;
}

/** Defines the lifetime and persistence expectations for agent state. */
export interface SessionPolicy {
  mode: "ephemeral" | "durable";
  restoreState?: boolean;
}

/** The single definition format for every agent in the platform. */
export interface AgentDefinition {
  id: string;
  description: string;
  systemPrompt: PromptSource;
  model: ModelPolicy;
  tools: string[];
  skills?: SkillSelectionPolicy;
  allowedDelegates?: string[];
  sessionPolicy?: SessionPolicy;
}
