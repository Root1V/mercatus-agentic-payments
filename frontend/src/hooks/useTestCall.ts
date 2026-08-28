import { useMutation, useQueryClient } from "@tanstack/react-query";
import { runTestCall } from "@/api/testCall";
import type { TestCallRequest } from "@/types/testCall";

export function useTestCall() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: TestCallRequest) => runTestCall(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ledger"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
