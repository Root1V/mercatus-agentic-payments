import type { ProtocolName } from "./protocol";

export interface Agent {
  id: number;
  owner_user_id: number;
  name: string;
  instructions: string;
  llm_model: string;
  protocol: ProtocolName;
  spend_limit_usd: string | null;
  created_at: string;
}

export interface CreateAgentInput {
  name: string;
  instructions?: string;
  llm_model: string;
  protocol: ProtocolName;
  spend_limit_usd?: string | null;
}

export interface LlmModel {
  id: string;
  object: string;
  owned_by: string;
  context_length?: number;
  family?: string;
  quantization?: string;
  modality?: string;
}

export interface AgentConversation {
  id: number;
  agent_id: number;
  title: string;
  created_at: string;
}

export type TraceAction = "search_catalog" | "call_service" | "final_answer";

export interface TraceStep {
  turn: number;
  thought: string;
  action: TraceAction;
  action_input: Record<string, unknown>;
  observation: unknown;
}

export type AgentMessageRole = "user" | "agent";

export interface AgentMessage {
  id: number;
  conversation_id: number;
  role: AgentMessageRole;
  content: string;
  trace: TraceStep[] | null;
  total_spent_usd: string | null;
  created_at: string;
}
