import { useMutation } from "@tanstack/react-query";
import { fetchSellerPreview } from "@/api/sellerPreview";
import type { ProtocolName } from "@/types/protocol";

export function useSellerPreview() {
  return useMutation({
    mutationFn: (protocol: ProtocolName) => fetchSellerPreview(protocol),
  });
}
