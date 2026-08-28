"""Prueba `PayingAgent` de punta a punta contra el vendedor de ejemplo real,
para AMBOS protocolos (fixture `seller_server` parametrizada en conftest.py)."""

from __future__ import annotations

import pytest

from agent_commerce.catalog.models import ServiceListing
from agent_commerce.catalog.registry import InMemoryServiceRegistry
from agent_commerce.client.paying_agent import NoMatchingServiceError, PayingAgent
from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner


def _catalog_for(seller_server) -> InMemoryServiceRegistry:
    listing = ServiceListing(
        id="text-summarizer",
        name="Text Summarizer",
        description="Resume un texto a N oraciones clave.",
        method="POST",
        url=f"{seller_server.base_url}/summarize",
        price_usd="$0.001",
        capability_tags=["summarize", "text"],
        protocols=[seller_server.protocol.name],
    )
    return InMemoryServiceRegistry([listing])


async def test_paying_agent_discovers_and_pays_the_service(seller_server) -> None:
    catalog = _catalog_for(seller_server)
    buyer = LocalEoaSigner()

    async with PayingAgent(protocol=seller_server.protocol, signer=buyer, catalog=catalog) as agent:
        discovered = await agent.discover("summarize")
        assert len(discovered) == 1

        result = await agent.call_service("summarize", {"text": "Uno. Dos. Tres.", "max_sentences": 1})

    assert "summary" in result.data
    assert result.price_paid_usd is not None
    assert result.listing.id == "text-summarizer"
    assert result.receipt is not None
    assert result.receipt.payer.lower() == buyer.address.lower()


async def test_paying_agent_raises_when_no_service_matches(seller_server) -> None:
    catalog = _catalog_for(seller_server)
    buyer = LocalEoaSigner()

    async with PayingAgent(protocol=seller_server.protocol, signer=buyer, catalog=catalog) as agent:
        with pytest.raises(NoMatchingServiceError):
            await agent.call_service("this-capability-does-not-exist")
