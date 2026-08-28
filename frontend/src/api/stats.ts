import { apiClient } from "./client";
import type { DashboardStats } from "@/types/stats";

export async function fetchStats(): Promise<DashboardStats> {
  const { data } = await apiClient.get<DashboardStats>("/api/stats");
  return data;
}
