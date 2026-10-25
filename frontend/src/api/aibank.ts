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

export async function createConsentRequest(input: CreateConsentRequestInput): Promise<ConsentRequest> {
  const { data } = await apiClient.post<ConsentRequest>(`${BASE}/consent-requests`, input);
  return data;
}

export async function fetchConsentRequest(id: string): Promise<ConsentRequest> {
  const { data } = await apiClient.get<ConsentRequest>(`${BASE}/consent-requests/${id}`);
  return data;
}

export async function activateConsentRequest(id: string): Promise<WalletSettings> {
  const { data } = await apiClient.post<WalletSettings>(`${BASE}/consent-requests/${id}/activate`);
  return data;
}

export async function fetchAibankMandate(): Promise<AibankMandateState> {
  const { data } = await apiClient.get<AibankMandateState>(`${BASE}/mandate`);
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

export async function simulateMandateRevocation(): Promise<AibankMandate> {
  const { data } = await apiClient.post<AibankMandate>(`${BASE}/mandate/simulate-revocation`);
  return data;
}
