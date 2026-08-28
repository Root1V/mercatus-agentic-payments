from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from agent_commerce.catalog.models import ServiceListing
from agent_commerce.dashboard.adapters.sql_catalog_store import SqlCatalogStore

_CATALOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalog.sample.json"


def _sample_listing(listing_id: str = "test-service") -> ServiceListing:
    return ServiceListing(
        id=listing_id,
        name="Test Service",
        description="Un servicio de prueba.",
        method="POST",
        url="http://127.0.0.1:9999/test",
        price_usd="$0.01",
        capability_tags=["test"],
        protocols=["x402"],
    )


def test_create_list_get_delete(db_session: Session) -> None:
    store = SqlCatalogStore(db_session)
    assert store.list_all() == []

    created = store.create(_sample_listing())
    assert created.id == "test-service"

    assert [listing.id for listing in store.list_all()] == ["test-service"]
    fetched = store.get("test-service")
    assert fetched is not None
    assert fetched.name == "Test Service"

    assert store.get("no-existe") is None

    assert store.delete("test-service") is True
    assert store.list_all() == []
    assert store.delete("test-service") is False


def test_update_existing_listing(db_session: Session) -> None:
    store = SqlCatalogStore(db_session)
    store.create(_sample_listing())

    updated_listing = _sample_listing()
    updated_listing.name = "Renamed Service"
    updated_listing.price_usd = "$0.05"
    updated_listing.capability_tags = ["renamed", "test"]

    updated = store.update("test-service", updated_listing)
    assert updated is not None
    assert updated.name == "Renamed Service"
    assert updated.price_usd == "$0.05"
    assert updated.capability_tags == ["renamed", "test"]

    fetched = store.get("test-service")
    assert fetched is not None
    assert fetched.name == "Renamed Service"


def test_update_missing_listing_returns_none(db_session: Session) -> None:
    store = SqlCatalogStore(db_session)
    assert store.update("no-existe", _sample_listing("no-existe")) is None


def test_seed_from_json_if_empty_inserts_once(db_session: Session) -> None:
    store = SqlCatalogStore(db_session)

    inserted_first = store.seed_from_json_if_empty(str(_CATALOG_PATH))
    assert inserted_first >= 1
    assert len(store.list_all()) == inserted_first

    inserted_second = store.seed_from_json_if_empty(str(_CATALOG_PATH))
    assert inserted_second == 0
    assert len(store.list_all()) == inserted_first


def test_seeded_listings_are_marked_is_seed(db_session: Session) -> None:
    from agent_commerce.db.models import CatalogListingModel

    store = SqlCatalogStore(db_session)
    store.seed_from_json_if_empty(str(_CATALOG_PATH))

    model = db_session.get(CatalogListingModel, "text-summarizer")
    assert model is not None
    assert model.is_seed is True

    store.create(_sample_listing("manual-entry"), is_seed=False)
    manual_model = db_session.get(CatalogListingModel, "manual-entry")
    assert manual_model is not None
    assert manual_model.is_seed is False
