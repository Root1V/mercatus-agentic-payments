import { apiClient } from "./client";
import type { ProtocolInfo } from "@/types/protocol";

export async function fetchProtocols(): Promise<ProtocolInfo[]> {
  const { data } = await apiClient.get<ProtocolInfo[]>("/api/protocols");
  return data;
}
