"""`CatalogStore` en memoria -- para tests, sin Postgres."""

from __future__ import annotations

import json
from pathlib import Path

from agent_commerce.catalog.models import ServiceListing


class InMemoryCatalogStore:
    def __init__(self, listings: list[ServiceListing] | None = None) -> None:
        self._by_id: dict[str, ServiceListing] = {listing.id: listing for listing in (listings or [])}

    def list_all(self) -> list[ServiceListing]:
        return sorted(self._by_id.values(), key=lambda listing: listing.id)

    def get(self, listing_id: str) -> ServiceListing | None:
        return self._by_id.get(listing_id)

    def create(self, listing: ServiceListing, *, is_seed: bool = False) -> ServiceListing:
        self._by_id[listing.id] = listing
        return listing

    def update(self, listing_id: str, listing: ServiceListing) -> ServiceListing | None:
        if listing_id not in self._by_id:
            return None
        self._by_id[listing_id] = listing
        return listing

    def delete(self, listing_id: str) -> bool:
        return self._by_id.pop(listing_id, None) is not None

    def seed_from_json_if_empty(self, path: str) -> int:
        if self._by_id:
            return 0
        entries = json.loads(Path(path).read_text())
        for entry in entries:
            listing = ServiceListing.model_validate(entry)
            self.create(listing, is_seed=True)
        return len(entries)
