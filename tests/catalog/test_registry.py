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


@pytest.mark.parametrize(
    "query",
    [
        "resumen",  # variante en español de "resume" (la descripción arranca "Resume un texto...")
        "summary",  # variante de "summarize" (el capability_tag), no substring literal
        "texto resumen",  # consulta de varias palabras, alcanza con que una matchee
        "TEXT",  # insensible a mayúsculas, ya cubierto, pero confirmá con el tokenizer nuevo
    ],
)
async def test_search_matches_word_variants_not_just_literal_substring(query: str) -> None:
    """Un agente puede pedir "resumen" cuando el catálogo dice "resume", o
    "summary" cuando el tag es "summarize" -- son la misma raíz de palabra,
    no la misma cadena literal. Reproduce consultas reales que un agente
    generó y que con el matching viejo (substring exacto) no encontraban
    nada."""
    registry = InMemoryServiceRegistry.from_json_file(_CATALOG_PATH)
    results = await registry.search(query)
    assert any(listing.id == "text-summarizer" for listing in results)


async def test_search_does_not_match_unrelated_short_words() -> None:
    registry = InMemoryServiceRegistry.from_json_file(_CATALOG_PATH)
    results = await registry.search("this does not exist anywhere near it")
    assert results == []


async def test_get_unknown_service_raises() -> None:
    registry = InMemoryServiceRegistry.from_json_file(_CATALOG_PATH)
    with pytest.raises(ServiceNotFoundError):
        await registry.get("no-such-service")
