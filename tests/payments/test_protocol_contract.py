"""Contrato compartido: cualquier `PaymentProtocol` (x402, AP2, futuros) debe
producir el mismo resultado observable desde `PayingAgent` -- 402 sin pago,
200 + `PaymentReceipt` con pago -- para que cambiar de protocolo sea
transparente para el código de negocio. Reusa la fixture `seller_server`
(parametrizada por protocolo en conftest.py) en vez de repetir setup."""

from __future__ import annotations

import httpx

from agent_commerce.payments.protocols.base import BuyerClient, PaymentProtocol
from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner


async def test_protocol_instance_satisfies_the_port(seller_server) -> None:
    assert isinstance(seller_server.protocol, PaymentProtocol)


async def test_buyer_client_satisfies_the_port(seller_server) -> None:
    buyer_client = seller_server.protocol.build_buyer_client(LocalEoaSigner())
    try:
        assert isinstance(buyer_client, BuyerClient)
    finally:
        await buyer_client.aclose()


async def test_unpaid_vs_paid_shape_is_identical_across_protocols(seller_server) -> None:
    async with httpx.AsyncClient() as plain:
        unpaid = await plain.post(f"{seller_server.base_url}/summarize", json={"text": "hola"})
    assert unpaid.status_code == 402

    buyer_client = seller_server.protocol.build_buyer_client(LocalEoaSigner())
    try:
        paid = await buyer_client.request(
            "POST", f"{seller_server.base_url}/summarize", json={"text": "hola mundo"}
        )
    finally:
        await buyer_client.aclose()

    assert paid.status_code == 200
    assert paid.receipt is not None
    assert paid.receipt.protocol == seller_server.protocol.name
    assert paid.receipt.network == seller_server.settings.network
    assert paid.receipt.amount_usd > 0
