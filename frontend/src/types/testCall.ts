import type { ProtocolName } from "./protocol";

export interface TestCallRequest {
  protocol: ProtocolName;
  capability?: string;
  text: string;
  max_sentences?: number;
}

export interface PaymentReceiptDTO {
  protocol: string;
  network: string;
  payer: string;
  pay_to: string;
  amount_usd: string;
  settlement_id: string;
  wallet_backend: "local" | "circle" | "aibank" | null;
}

export interface TestCallResult {
  summary: string;
}

export interface TestCallResponse {
  ledger_entry_id: number;
  elapsed_ms: number;
  result: TestCallResult;
  receipt: PaymentReceiptDTO | null;
}

export interface SellerPreviewResponse {
  status_code: number;
  body: unknown;
  pay_to: string;
  price_usd: string;
  endpoint: string;
}
