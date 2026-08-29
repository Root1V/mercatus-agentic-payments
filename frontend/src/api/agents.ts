import { apiClient } from "./client";
import type {
  Agent,
  AgentConversation,
  AgentMessage,
  CreateAgentInput,
  LlmModel,
  LlmSettings,
  UpdateLlmSettingsInput,
} from "@/types/agent";

export async function fetchAgents(): Promise<Agent[]> {
  const { data } = await apiClient.get<Agent[]>("/api/agents");
  return data;
}

export async function createAgent(input: CreateAgentInput): Promise<Agent> {
  const { data } = await apiClient.post<Agent>("/api/agents", input);
  return data;
}

export async function updateAgent(id: number, input: CreateAgentInput): Promise<Agent> {
  const { data } = await apiClient.put<Agent>(`/api/agents/${id}`, input);
  return data;
}

export async function deleteAgent(id: number): Promise<void> {
  await apiClient.delete(`/api/agents/${id}`);
}

export async function fetchLlmModels(options?: { includeAll?: boolean }): Promise<LlmModel[]> {
  const { data } = await apiClient.get<{ models: LlmModel[] }>("/api/agents/llm-models", {
    params: options?.includeAll ? { include_all: true } : undefined,
  });
  return data.models;
}

export async function fetchLlmSettings(): Promise<LlmSettings> {
  const { data } = await apiClient.get<LlmSettings>("/api/admin/llm-settings");
  return data;
}

export async function updateLlmSettings(input: UpdateLlmSettingsInput): Promise<LlmSettings> {
  const { data } = await apiClient.put<LlmSettings>("/api/admin/llm-settings", input);
  return data;
}

export async function fetchConversations(agentId: number): Promise<AgentConversation[]> {
  const { data } = await apiClient.get<AgentConversation[]>(`/api/agents/${agentId}/conversations`);
  return data;
}

export async function createConversation(agentId: number, title: string): Promise<AgentConversation> {
  const { data } = await apiClient.post<AgentConversation>(`/api/agents/${agentId}/conversations`, {
    title,
  });
  return data;
}

export async function fetchMessages(agentId: number, conversationId: number): Promise<AgentMessage[]> {
  const { data } = await apiClient.get<AgentMessage[]>(
    `/api/agents/${agentId}/conversations/${conversationId}/messages`,
  );
  return data;
}

export async function sendMessage(
  agentId: number,
  conversationId: number,
  content: string,
): Promise<AgentMessage> {
  const { data } = await apiClient.post<AgentMessage>(
    `/api/agents/${agentId}/conversations/${conversationId}/messages`,
    { content },
  );
  return data;
}
