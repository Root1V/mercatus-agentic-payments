import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchWalletSettings, updateWalletSettings } from "@/api/wallet";
import type { UpdateWalletSettingsInput } from "@/types/wallet";

export function useWalletSettings() {
  return useQuery({ queryKey: ["wallet-settings"], queryFn: fetchWalletSettings });
}

export function useUpdateWalletSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateWalletSettingsInput) => updateWalletSettings(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wallet-settings"] });
      queryClient.invalidateQueries({ queryKey: ["protocols"] });
    },
  });
}
