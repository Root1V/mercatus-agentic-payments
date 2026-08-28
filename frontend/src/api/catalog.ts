import { apiClient } from "./client";
import type {
  CatalogListing,
  CreateCatalogListingInput,
  UpdateCatalogListingInput,
} from "@/types/catalog";

export async function fetchCatalog(): Promise<CatalogListing[]> {
  const { data } = await apiClient.get<CatalogListing[]>("/api/catalog");
  return data;
}

export async function createCatalogListing(
  input: CreateCatalogListingInput,
): Promise<CatalogListing> {
  const { data } = await apiClient.post<CatalogListing>("/api/catalog", input);
  return data;
}

export async function updateCatalogListing(
  id: string,
  input: UpdateCatalogListingInput,
): Promise<CatalogListing> {
  const { data } = await apiClient.put<CatalogListing>(
    `/api/catalog/${encodeURIComponent(id)}`,
    input,
  );
  return data;
}

export async function deleteCatalogListing(id: string): Promise<void> {
  await apiClient.delete(`/api/catalog/${encodeURIComponent(id)}`);
}
