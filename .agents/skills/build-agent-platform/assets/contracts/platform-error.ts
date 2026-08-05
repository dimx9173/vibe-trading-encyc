export type PlatformErrorCode =
  | "AGENT_NOT_FOUND"
  | "DELEGATION_NOT_ALLOWED"
  | "TOOL_NOT_REGISTERED"
  | "TOOL_INPUT_INVALID"
  | "SKILL_NOT_FOUND"
  | "SKILL_AMBIGUOUS"
  | "SKILL_INVALID"
  | "SKILL_RESOURCE_INVALID"
  | "SKILL_DEPENDENCY_MISSING"
  | "SKILL_REFRESH_DISABLED"
  | "SESSION_BUSY"
  | "SESSION_RECOVERY_FAILED"
  | "INSFORGE_AUTH_EXPIRED"
  | "UPSTREAM_UNAVAILABLE"
  | "MCP_TOOL_FAILED";

export type PlatformErrorLayer =
  | "runtime"
  | "agent"
  | "tool"
  | "skill"
  | "session"
  | "insforge"
  | "bff"
  | "mcp";

/** A normalized, serializable failure returned across platform boundaries. */
export interface PlatformError {
  code: PlatformErrorCode;
  message: string;
  layer: PlatformErrorLayer;
  retryable: boolean;
  cause?: unknown;
  metadata?: Record<string, unknown>;
}
