import { isAxiosError } from "axios";

// Códigos de error de AIBank (doc 11 §7 y doc 13 §5, los mismos que emite la
// API real) que el comprador puede encontrar al pagar, explicados por quién
// los arregla -- el spec insiste en no colapsar
// "falta permiso" con "falta dinero": uno lo resuelve el titular, el otro
// fondeando.
const AIBANK_ERROR_EXPLANATIONS: Record<string, string> = {
  mandate_limit_exceeded:
    "El pago supera el permiso que dio el titular. No es falta de saldo: hay que pedirle una ampliación (o cobrar menos).",
  mandate_revoked: "El titular revocó el permiso. Hay que pedirle consentimiento de nuevo.",
  mandate_expired: "El permiso del titular venció. Hay que pedirle consentimiento de nuevo.",
  mandate_not_found:
    "El permiso guardado ya no existe en el banco (el banco simulado vive en memoria: ¿se reinició el dashboard?). Conectá la cuenta de nuevo.",
  mandate_account_not_covered: "La cuenta pagadora no es la que cubre el permiso del titular.",
  insufficient_funds: "La cuenta pagadora no tiene saldo suficiente.",
  consent_request_not_found: "La solicitud de permiso no existe o ya venció (vive una hora). Pedí una nueva.",
  consent_request_already_resolved: "El titular ya decidió sobre esta solicitud.",
  account_not_found: "Esa cuenta no existe en el banco (o no es de Mercatus). Dejá la sub-cuenta vacía para usar una propia.",
  account_frozen: "La cuenta está congelada por un control del banco y no admite movimientos.",
  // Contrato 1.1: cada pago va firmado por el agente dueño de la cuenta o del permiso.
  account_agent_scope:
    "Esa sub-cuenta no es de este agente: solo puede pagar desde ella el agente al que está atada. Dejá la sub-cuenta vacía para usar la del dashboard.",
  mandate_agent_scope: "El permiso del titular es de otro agente: pedí un permiso nuevo para este.",
  agent_signature_invalid: "El banco no reconoce la firma del agente (clave desconocida, retirada o agente dado de baja).",
  agent_revoked: "El agente está dado de baja en el banco.",
  malformed_request: "Faltan datos en la solicitud: el propósito es obligatorio.",
  // Canal del titular (la app del banco), con su propio vocabulario.
  limit_above_requested: "El titular puede conceder menos de lo pedido, nunca más.",
  already_resolved: "El titular ya decidió sobre esta solicitud.",
};

/** El mensaje que conviene mostrar: el `detail` que manda el backend (no el
 * genérico de axios, "Request failed with status code 502"), traducido a
 * una explicación cuando es un código conocido de AIBank. */
export function apiErrorMessage(error: unknown, fallback = "Error desconocido"): string {
  let detail: string | undefined;
  if (isAxiosError(error) && typeof error.response?.data?.detail === "string") {
    detail = error.response.data.detail;
  } else if (error instanceof Error) {
    detail = error.message;
  }
  if (!detail) return fallback;
  const code = Object.keys(AIBANK_ERROR_EXPLANATIONS).find((known) => detail.includes(known));
  return code ? AIBANK_ERROR_EXPLANATIONS[code] : detail;
}

export function isNotFoundError(error: unknown): boolean {
  return isAxiosError(error) && error.response?.status === 404;
}
