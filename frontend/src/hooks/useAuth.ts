import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchCurrentUser, login as loginRequest } from "@/api/auth";
import { clearStoredToken, getStoredToken, setStoredToken } from "@/api/client";

export function useCurrentUser() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchCurrentUser,
    enabled: Boolean(getStoredToken()),
    retry: false,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      loginRequest(username, password),
    onSuccess: (data) => {
      setStoredToken(data.access_token);
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useCallback(() => {
    clearStoredToken();
    queryClient.clear();
    window.location.assign("/login");
  }, [queryClient]);
}

export function useIsAuthenticated(): boolean {
  const [hasToken] = useState(() => Boolean(getStoredToken()));
  return hasToken;
}
