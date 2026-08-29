import { apiClient } from "./client";
import type { UpdateWalletSettingsInput, WalletSettings } from "@/types/wallet";

export async function fetchWalletSettings(): Promise<WalletSettings> {
  const { data } = await apiClient.get<WalletSettings>("/api/admin/wallet-settings");
  return data;
}

export async function updateWalletSettings(input: UpdateWalletSettingsInput): Promise<WalletSettings> {
  const { data } = await apiClient.put<WalletSettings>("/api/admin/wallet-settings", input);
  return data;
}
