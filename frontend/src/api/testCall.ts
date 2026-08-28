import { apiClient } from "./client";
import type { TestCallRequest, TestCallResponse } from "@/types/testCall";

export async function runTestCall(payload: TestCallRequest): Promise<TestCallResponse> {
  const { data } = await apiClient.post<TestCallResponse>("/api/test-call", payload);
  return data;
}
