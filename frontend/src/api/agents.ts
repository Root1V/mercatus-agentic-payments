import { apiClient } from "./client";
import type { Agent, AgentConversation, AgentMessage, CreateAgentInput, LlmModel } from "@/types/agent";

export async function fetchAgents(): Promise<Agent[]> {
  const { data } = await apiClient.get<Agent[]>("/api/agents");
  return data;
}

export async function createAgent(input: CreateAgentInput): Promise<Agent> {
  const { data } = await apiClient.post<Agent>("/api/agents", input);
  return data;
}

export async function deleteAgent(id: number): Promise<void> {
  await apiClient.delete(`/api/agents/${id}`);
}

export async function fetchLlmModels(): Promise<LlmModel[]> {
  const { data } = await apiClient.get<{ models: LlmModel[] }>("/api/agents/llm-models");
  return data.models;
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
