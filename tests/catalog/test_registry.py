from __future__ import annotations

from pathlib import Path

import pytest

from agent_commerce.catalog.registry import InMemoryServiceRegistry, ServiceNotFoundError

_CATALOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalog.sample.json"


async def test_loads_sample_catalog_from_json() -> None:
    registry = InMemoryServiceRegistry.from_json_file(_CATALOG_PATH)
    listing = await registry.get("text-summarizer")
    assert listing.name == "Text Summarizer"
    assert listing.price_usd == "$0.001"


async def test_search_matches_by_capability_tag() -> None:
    registry = InMemoryServiceRegistry.from_json_file(_CATALOG_PATH)
    results = await registry.search("nlp")
    assert any(listing.id == "text-summarizer" for listing in results)


async def test_search_with_no_match_returns_empty_list() -> None:
    registry = InMemoryServiceRegistry.from_json_file(_CATALOG_PATH)
    results = await registry.search("this-does-not-exist-anywhere")
    assert results == []


async def test_get_unknown_service_raises() -> None:
    registry = InMemoryServiceRegistry.from_json_file(_CATALOG_PATH)
    with pytest.raises(ServiceNotFoundError):
        await registry.get("no-such-service")
