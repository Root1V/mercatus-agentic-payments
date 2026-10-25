import { useMutation, useQueryClient } from "@tanstack/react-query";
import { runTestCall } from "@/api/testCall";
import type { TestCallRequest } from "@/types/testCall";

export function useTestCall() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: TestCallRequest) => runTestCall(payload),
    // También al fallar: un pago rechazado por el banco puede haber
    // cambiado el estado del mandato (p. ej. marcarlo vencido).
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["aibank-mandate"] });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ledger"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
