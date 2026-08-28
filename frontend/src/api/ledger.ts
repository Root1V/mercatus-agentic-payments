import { apiClient } from "./client";
import type { LedgerEntry } from "@/types/ledger";

export async function fetchLedger(limit = 50): Promise<LedgerEntry[]> {
  const { data } = await apiClient.get<LedgerEntry[]>("/api/ledger", { params: { limit } });
  return data;
}
