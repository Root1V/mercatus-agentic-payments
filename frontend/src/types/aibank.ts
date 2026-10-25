// AIBank modelo B (RM-18): conectar la cuenta propia de un cliente de AIBank
// con el flujo de `13-spec-modelos-a-y-b.md` §3. Importes en USD como
// string decimal, tal como los devuelve el backend.

export type ConsentRequestStatus = "pending" | "approved" | "rejected";

export interface ConsentRequest {
  consent_request_id: string;
  // Lo que el cliente abre en la app de AIBank (enlace o QR).
  handoff_code: string;
  status: ConsentRequestStatus;
  currency: string;
  max_per_operation_usd: string;
  max_total_usd: string;
  purpose: string;
  expires_at: string;
  // Solo presentes una vez aprobada: la cuenta la elige el titular, no
  // Mercatus.
  mandate_id: string | null;
  account_id: string | null;
}

export interface CreateConsentRequestInput {
  max_per_operation_usd: string;
  max_total_usd: string;
  purpose: string;
}

export interface SimulateApprovalInput {
  account_id: string;
  // undefined = conceder exactamente lo pedido.
  max_per_operation_usd?: string;
  max_total_usd?: string;
}

export type MandateStatus = "active" | "revoked" | "expired";

export interface AibankMandate {
  mandate_id: string;
  account_id: string;
  currency: string;
  status: MandateStatus;
  max_per_operation_usd: string;
  max_total_usd: string;
  // Se deriva de las autorizaciones vivas: una retención sin capturar ya
  // consume el tope, y un reembolso lo libera.
  consumed_usd: string;
  remaining_usd: string;
  expires_at: string;
}

export type AibankMandateState =
  | { configured: false }
  // El mandato guardado ya no existe en el banco simulado (vive en memoria:
  // un reinicio del dashboard lo pierde).
  | { configured: true; found: false; mandate_id: string }
  | ({ configured: true; found: true } & AibankMandate);
