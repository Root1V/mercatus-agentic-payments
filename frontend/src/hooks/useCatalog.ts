import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCatalogListing,
  deleteCatalogListing,
  fetchCatalog,
  updateCatalogListing,
} from "@/api/catalog";
import type { CreateCatalogListingInput, UpdateCatalogListingInput } from "@/types/catalog";

const CATALOG_KEY = ["catalog"];

export function useCatalog() {
  return useQuery({
    queryKey: CATALOG_KEY,
    queryFn: fetchCatalog,
  });
}

export function useCreateCatalogListing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateCatalogListingInput) => createCatalogListing(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CATALOG_KEY });
    },
  });
}

export function useUpdateCatalogListing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateCatalogListingInput }) =>
      updateCatalogListing(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CATALOG_KEY });
    },
  });
}

export function useDeleteCatalogListing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteCatalogListing(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CATALOG_KEY });
    },
  });
}
