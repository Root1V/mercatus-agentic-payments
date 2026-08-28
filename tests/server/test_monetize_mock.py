"""Prueba `server.monetize.mount_payments` (vía el vendedor de ejemplo) contra
AMBOS protocolos -- la fixture `seller_server` (tests/conftest.py) está
parametrizada por `protocol_name`, así este mismo test corre dos veces."""

from __future__ import annotations

from decimal import Decimal

import httpx

from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner


async def test_summarize_requires_payment_then_succeeds(seller_server) -> None:
    async with httpx.AsyncClient() as plain:
        unpaid = await plain.post(f"{seller_server.base_url}/summarize", json={"text": "hola"})
    assert unpaid.status_code == 402

    buyer = LocalEoaSigner()
    buyer_client = seller_server.protocol.build_buyer_client(buyer)
    try:
        result = await buyer_client.request(
            "POST",
            f"{seller_server.base_url}/summarize",
            json={"text": "Frase uno. Frase dos. Frase tres.", "max_sentences": 1},
        )
    finally:
        await buyer_client.aclose()

    assert result.status_code == 200
    assert "summary" in result.json_body
    assert result.receipt is not None
    assert result.receipt.amount_usd == Decimal("0.001")


async def test_catalog_entry_self_describes(seller_server) -> None:
    async with httpx.AsyncClient() as plain:
        response = await plain.get(f"{seller_server.base_url}/catalog-entry")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "text-summarizer"
    assert body["protocols"] == [seller_server.protocol.name]
