import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createAgent,
  createConversation,
  deleteAgent,
  fetchAgents,
  fetchConversations,
  fetchLlmModels,
  fetchLlmSettings,
  fetchMessages,
  sendMessage,
  updateAgent,
  updateLlmSettings,
} from "@/api/agents";
import type { CreateAgentInput, UpdateLlmSettingsInput } from "@/types/agent";

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

export function useUpdateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: CreateAgentInput }) => updateAgent(id, input),
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
  // Sin reintento: un 500 acá significa que el LLM no está configurado
  // (ni en la DB ni por variables de entorno), no una falla transitoria de
  // red -- reintentar nunca lo va a arreglar, solo demora mostrar el error.
  return useQuery({ queryKey: ["llm-models"], queryFn: () => fetchLlmModels(), retry: false });
}

// Usado solo por el diálogo de configuración: la lista SIN filtrar por
// `allowed_models`, para poder elegir cuáles habilitar. Deshabilitada salvo
// que se pida explícitamente (`enabled`) -- no tiene sentido pedirla si la
// conexión todavía no está guardada.
export function useAllLlmModels(enabled: boolean) {
  return useQuery({
    queryKey: ["llm-models", "all"],
    queryFn: () => fetchLlmModels({ includeAll: true }),
    retry: false,
    enabled,
  });
}

export function useLlmSettings() {
  return useQuery({ queryKey: ["llm-settings"], queryFn: fetchLlmSettings });
}

export function useUpdateLlmSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateLlmSettingsInput) => updateLlmSettings(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-settings"] });
      queryClient.invalidateQueries({ queryKey: ["llm-models"] });
    },
  });
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
