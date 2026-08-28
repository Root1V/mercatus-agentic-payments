export type ProtocolName = "x402" | "ap2";

export interface ProtocolInfo {
  name: ProtocolName;
  label: string;
  description: string;
  network: string;
  mode: "mock" | "testnet";
  seller_pay_to: string;
  buyer_address: string;
  endpoint: string;
}
