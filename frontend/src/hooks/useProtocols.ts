import { useQuery } from "@tanstack/react-query";
import { fetchProtocols } from "@/api/protocols";

export function useProtocols() {
  return useQuery({
    queryKey: ["protocols"],
    queryFn: fetchProtocols,
  });
}
