import { apiClient } from "./client";
import type { ProtocolName } from "@/types/protocol";
import type { SellerPreviewResponse } from "@/types/testCall";

export async function fetchSellerPreview(protocol: ProtocolName): Promise<SellerPreviewResponse> {
  const { data } = await apiClient.get<SellerPreviewResponse>(`/api/seller-preview/${protocol}`);
  return data;
}
