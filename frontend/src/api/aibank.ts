import { apiClient } from "./client";
import type {
  AibankMandate,
  AibankMandateState,
  ConsentRequest,
  CreateConsentRequestInput,
  SimulateApprovalInput,
} from "@/types/aibank";
import type { WalletSettings } from "@/types/wallet";

const BASE = "/api/admin/aibank";

// `agentId`: el agente del playground al que pertenece el permiso (contrato
// 1.1 de AIBank: cada permiso es de UN agente). Sin él, es el del comprador
// del dashboard ("Probar comprador").
function agentParams(agentId?: number) {
  return agentId === undefined ? undefined : { agent_id: agentId };
}

export async function createConsentRequest(input: CreateConsentRequestInput, agentId?: number): Promise<ConsentRequest> {
  const { data } = await apiClient.post<ConsentRequest>(`${BASE}/consent-requests`, input, {
    params: agentParams(agentId),
  });
  return data;
}

export async function fetchConsentRequest(id: string): Promise<ConsentRequest> {
  const { data } = await apiClient.get<ConsentRequest>(`${BASE}/consent-requests/${id}`);
  return data;
}

export async function activateConsentRequest(id: string, agentId?: number): Promise<WalletSettings> {
  const { data } = await apiClient.post<WalletSettings>(`${BASE}/consent-requests/${id}/activate`, undefined, {
    params: agentParams(agentId),
  });
  return data;
}

export async function fetchAibankMandate(agentId?: number): Promise<AibankMandateState> {
  const { data } = await apiClient.get<AibankMandateState>(`${BASE}/mandate`, { params: agentParams(agentId) });
  return data;
}

// --- Simulador: reemplaza la app de AIBank, donde en la vida real decide
// el titular autenticándose con su propio dispositivo. ---

export async function simulateTitularApproval(id: string, input: SimulateApprovalInput): Promise<AibankMandate> {
  const { data } = await apiClient.post<AibankMandate>(`${BASE}/consent-requests/${id}/simulate-approval`, input);
  return data;
}

export async function simulateTitularRejection(id: string): Promise<ConsentRequest> {
  const { data } = await apiClient.post<ConsentRequest>(`${BASE}/consent-requests/${id}/simulate-rejection`);
  return data;
}

export async function simulateMandateRevocation(agentId?: number): Promise<AibankMandate> {
  const { data } = await apiClient.post<AibankMandate>(`${BASE}/mandate/simulate-revocation`, undefined, {
    params: agentParams(agentId),
  });
  return data;
}
