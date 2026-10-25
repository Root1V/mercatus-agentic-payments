import { isAxiosError } from "axios";

// Códigos de error de AIBank (doc 13 §5) que el comprador puede encontrar al
// pagar, explicados por quién los arregla -- el spec insiste en no colapsar
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
  cannot_raise_requested_limits: "El titular puede conceder menos de lo pedido, nunca más.",
  malformed_request: "Faltan datos en la solicitud: el propósito es obligatorio.",
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
