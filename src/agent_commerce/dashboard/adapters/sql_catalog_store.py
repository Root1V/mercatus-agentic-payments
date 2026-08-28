"""`CatalogStore` respaldado por Postgres."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_commerce.catalog.models import ServiceListing
from agent_commerce.db.models import CatalogListingModel


def _to_listing(model: CatalogListingModel) -> ServiceListing:
    return ServiceListing(
        id=model.id,
        name=model.name,
        description=model.description,
        method=model.method,  # type: ignore[arg-type]
        url=model.url,  # type: ignore[arg-type]
        price_usd=model.price_usd,
        capability_tags=list(model.capability_tags),
        protocols=list(model.protocols),
        provider_name=model.provider_name,
    )


class SqlCatalogStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_all(self) -> list[ServiceListing]:
        stmt = select(CatalogListingModel).order_by(CatalogListingModel.id)
        return [_to_listing(m) for m in self._db.execute(stmt).scalars().all()]

    def get(self, listing_id: str) -> ServiceListing | None:
        model = self._db.get(CatalogListingModel, listing_id)
        return _to_listing(model) if model is not None else None

    def create(self, listing: ServiceListing, *, is_seed: bool = False) -> ServiceListing:
        model = CatalogListingModel(
            id=listing.id,
            name=listing.name,
            description=listing.description,
            method=listing.method,
            url=str(listing.url),
            price_usd=listing.price_usd,
            capability_tags=list(listing.capability_tags),
            protocols=list(listing.protocols),
            provider_name=listing.provider_name,
            is_seed=is_seed,
        )
        self._db.add(model)
        self._db.commit()
        self._db.refresh(model)
        return _to_listing(model)

    def update(self, listing_id: str, listing: ServiceListing) -> ServiceListing | None:
        model = self._db.get(CatalogListingModel, listing_id)
        if model is None:
            return None
        model.name = listing.name
        model.description = listing.description
        model.method = listing.method
        model.url = str(listing.url)
        model.price_usd = listing.price_usd
        model.capability_tags = list(listing.capability_tags)
        model.protocols = list(listing.protocols)
        model.provider_name = listing.provider_name
        self._db.commit()
        self._db.refresh(model)
        return _to_listing(model)

    def delete(self, listing_id: str) -> bool:
        model = self._db.get(CatalogListingModel, listing_id)
        if model is None:
            return False
        self._db.delete(model)
        self._db.commit()
        return True

    def seed_from_json_if_empty(self, path: str) -> int:
        has_any = self._db.execute(select(CatalogListingModel.id).limit(1)).first() is not None
        if has_any:
            return 0

        entries = json.loads(Path(path).read_text())
        inserted = 0
        for entry in entries:
            listing = ServiceListing.model_validate(entry)
            self.create(listing, is_seed=True)
            inserted += 1
        return inserted
