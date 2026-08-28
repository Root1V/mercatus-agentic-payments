import { useQuery } from "@tanstack/react-query";
import { fetchLedger } from "@/api/ledger";

export function useLedger(limit = 50) {
  return useQuery({
    queryKey: ["ledger", limit],
    queryFn: () => fetchLedger(limit),
    refetchInterval: 10_000,
  });
}
