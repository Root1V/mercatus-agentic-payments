export interface DashboardStats {
  mode: "mock" | "testnet";
  network: string;
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  total_paid_usd: string;
  calls_by_protocol: Record<string, number>;
}
