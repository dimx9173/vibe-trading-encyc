export interface RuntimeEventBase {
  type: string;
  timestamp: string;
  runId: string;
  sessionId: string;
  agentId: string;
}

export interface TurnStarted extends RuntimeEventBase {
  type: "turn_started";
}

export interface TextDelta extends RuntimeEventBase {
  type: "text_delta";
  text: string;
}

export interface ToolCallStarted extends RuntimeEventBase {
  type: "tool_call_started";
  toolCallId: string;
  toolName: string;
}

export interface ToolCallCompleted extends RuntimeEventBase {
  type: "tool_call_completed";
  toolCallId: string;
  toolName: string;
  success: boolean;
}

export interface DelegationStarted extends RuntimeEventBase {
  type: "delegation_started";
  childRunId: string;
  targetAgentId: string;
}

export interface DelegationCompleted extends RuntimeEventBase {
  type: "delegation_completed";
  childRunId: string;
  targetAgentId: string;
  success: boolean;
}

export interface TurnCompleted extends RuntimeEventBase {
  type: "turn_completed";
}

export interface TurnFailed extends RuntimeEventBase {
  type: "turn_failed";
  errorCode: string;
  message: string;
}

/** The stable event vocabulary emitted by the runtime adapter. */
export type RuntimeEvent =
  | TurnStarted
  | TextDelta
  | ToolCallStarted
  | ToolCallCompleted
  | DelegationStarted
  | DelegationCompleted
  | TurnCompleted
  | TurnFailed;
