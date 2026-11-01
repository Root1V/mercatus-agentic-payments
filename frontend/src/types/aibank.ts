// AIBank modelo B (RM-18): conectar la cuenta propia de un cliente de AIBank
// con el flujo de `13-spec-modelos-a-y-b.md` §3. Importes en USD como
// string decimal, tal como los devuelve el backend.

// "expired": pasó la hora de vida sin que el titular decidiera.
export type ConsentRequestStatus = "pending" | "approved" | "rejected" | "expired";

export interface ConsentRequest {
  consent_request_id: string;
  // Lo que el cliente abre en la app de AIBank (enlace o QR).
  handoff_code: string;
  status: ConsentRequestStatus;
  currency: string;
  // Lo pedido lo guarda el dashboard (el banco no lo devuelve al consultar):
  // null si la solicitud se pidió antes de un reinicio.
  max_per_operation_usd: string | null;
  max_total_usd: string | null;
  purpose: string | null;
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
  // La cuenta no se elige acá: el simulador abre la de un titular de prueba
  // (con saldo), como lo haría una persona real en la app del banco.
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
  // null = sin tope (el titular puede conceder un permiso sin tope si no se pidió uno).
  max_per_operation_usd: string | null;
  max_total_usd: string | null;
  // Se deriva de las autorizaciones vivas: una retención sin capturar ya
  // consume el tope, y un reembolso lo libera.
  consumed_usd: string;
  remaining_usd: string | null;
  expires_at: string;
}

export type AibankMandateState =
  | { configured: false }
  // El mandato guardado ya no existe en el banco simulado (vive en memoria:
  // un reinicio del dashboard lo pierde).
  | { configured: true; found: false; mandate_id: string }
  | ({ configured: true; found: true } & AibankMandate);
