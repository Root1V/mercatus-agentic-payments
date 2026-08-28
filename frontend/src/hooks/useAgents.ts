import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createAgent,
  createConversation,
  deleteAgent,
  fetchAgents,
  fetchConversations,
  fetchLlmModels,
  fetchMessages,
  sendMessage,
} from "@/api/agents";
import type { CreateAgentInput } from "@/types/agent";

const AGENTS_KEY = ["agents"];

export function useAgents() {
  return useQuery({ queryKey: AGENTS_KEY, queryFn: fetchAgents });
}

export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateAgentInput) => createAgent(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AGENTS_KEY }),
  });
}

export function useDeleteAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteAgent(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AGENTS_KEY }),
  });
}

export function useLlmModels() {
  // Sin reintento: un 500 acá significa que Prometheus no está configurado
  // (variables de entorno faltantes), no una falla transitoria de red --
  // reintentar nunca lo va a arreglar, solo demora mostrar el error.
  return useQuery({ queryKey: ["llm-models"], queryFn: fetchLlmModels, retry: false });
}

export function useConversations(agentId: number | null) {
  return useQuery({
    queryKey: ["conversations", agentId],
    queryFn: () => fetchConversations(agentId as number),
    enabled: agentId !== null,
  });
}

export function useCreateConversation(agentId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (title: string) => createConversation(agentId as number, title),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations", agentId] }),
  });
}

export function useMessages(agentId: number | null, conversationId: number | null) {
  return useQuery({
    queryKey: ["messages", agentId, conversationId],
    queryFn: () => fetchMessages(agentId as number, conversationId as number),
    enabled: agentId !== null && conversationId !== null,
  });
}

export function useSendMessage(agentId: number | null, conversationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: string) => sendMessage(agentId as number, conversationId as number, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["messages", agentId, conversationId] });
      queryClient.invalidateQueries({ queryKey: ["ledger"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
