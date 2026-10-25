import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  activateConsentRequest,
  createConsentRequest,
  fetchAibankMandate,
  fetchConsentRequest,
  simulateMandateRevocation,
  simulateTitularApproval,
  simulateTitularRejection,
} from "@/api/aibank";
import type { CreateConsentRequestInput, SimulateApprovalInput } from "@/types/aibank";

export const AIBANK_MANDATE_QUERY_KEY = ["aibank-mandate"] as const;

// Cada cuánto se consulta una solicitud pendiente. El banco no notifica
// (doc 13 §3.2: se consulta, no se notifica) y la decisión tarda lo que
// tarda una persona en mirar su teléfono -- 2 s es de sobra.
const CONSENT_POLL_MS = 2_000;

export function useAibankMandate(enabled: boolean) {
  return useQuery({ queryKey: AIBANK_MANDATE_QUERY_KEY, queryFn: fetchAibankMandate, enabled });
}

export function useConsentRequest(id: string | null) {
  return useQuery({
    queryKey: ["aibank-consent-request", id],
    queryFn: () => fetchConsentRequest(id as string),
    enabled: id !== null,
    // Una solicitud vencida devuelve 404: no tiene sentido reintentar.
    retry: false,
    refetchInterval: (query) => (query.state.data?.status === "pending" ? CONSENT_POLL_MS : false),
  });
}

export function useCreateConsentRequest() {
  return useMutation({ mutationFn: (input: CreateConsentRequestInput) => createConsentRequest(input) });
}

export function useActivateConsentRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => activateConsentRequest(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wallet-settings"] });
      queryClient.invalidateQueries({ queryKey: ["protocols"] });
      queryClient.invalidateQueries({ queryKey: AIBANK_MANDATE_QUERY_KEY });
    },
  });
}

export function useSimulateTitularApproval(id: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SimulateApprovalInput) => simulateTitularApproval(id as string, input),
    // El banco no avisa: la decisión se descubre consultando, igual que en
    // producción. Invalidar solo adelanta la próxima consulta.
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["aibank-consent-request", id] }),
  });
}

export function useSimulateTitularRejection(id: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => simulateTitularRejection(id as string),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["aibank-consent-request", id] }),
  });
}

export function useSimulateMandateRevocation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: simulateMandateRevocation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AIBANK_MANDATE_QUERY_KEY }),
  });
}
