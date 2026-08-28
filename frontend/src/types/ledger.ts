import type { ProtocolName } from "./protocol";

export interface LedgerEntry {
  id: number;
  timestamp: string;
  protocol: ProtocolName;
  capability: string;
  service_id: string;
  payer: string;
  pay_to: string;
  amount_usd: string;
  settlement_id: string;
  status: "ok" | "error";
  detail: string | null;
}
