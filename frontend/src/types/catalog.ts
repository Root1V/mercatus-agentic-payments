import type { ProtocolName } from "./protocol";

export interface CatalogListing {
  id: string;
  name: string;
  description: string;
  method: "GET" | "POST";
  url: string;
  price_usd: string;
  capability_tags: string[];
  protocols: ProtocolName[];
  provider_name: string;
}

export interface CreateCatalogListingInput {
  id: string;
  name: string;
  description: string;
  method: "GET" | "POST";
  url: string;
  price_usd: string;
  capability_tags: string[];
  protocols: ProtocolName[];
  provider_name?: string;
}

export interface UpdateCatalogListingInput {
  name: string;
  description: string;
  method: "GET" | "POST";
  url: string;
  price_usd: string;
  capability_tags: string[];
  protocols: ProtocolName[];
  provider_name?: string;
}
