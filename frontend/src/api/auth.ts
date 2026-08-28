import { apiClient } from "./client";
import type { CurrentUser, LoginResponse } from "@/types/auth";

export async function login(username: string, password: string): Promise<LoginResponse> {
  const body = new URLSearchParams({ username, password });
  const { data } = await apiClient.post<LoginResponse>("/api/auth/login", body, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return data;
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>("/api/auth/me");
  return data;
}
