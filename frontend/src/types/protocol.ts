export type ProtocolName = "x402" | "ap2";

export interface ProtocolInfo {
  name: ProtocolName;
  label: string;
  description: string;
  network: string;
  mode: "mock" | "testnet";
  seller_pay_to: string;
  // null cuando el backend de wallet del comprador (RM-19) está mal
  // configurado -- p. ej. "circle" elegido sin cargar todavía las credenciales.
  buyer_address: string | null;
  endpoint: string;
}
