"""Prueba el flujo AP2 (mandatos) liquidando de verdad sobre x402/Base Sepolia.

Mismas condiciones que `test_testnet_x402.py`: se salta salvo que corras
explícitamente con credenciales de testnet reales.

    AGENT_COMMERCE_MODE=testnet AGENT_COMMERCE_PROTOCOL=ap2 \\
    AGENT_COMMERCE_BUYER_PRIVATE_KEY=0x... AGENT_COMMERCE_SELLER_PRIVATE_KEY=0x... \\
    pytest -m testnet tests/integration/test_testnet_ap2.py
"""

from __future__ import annotations

import pytest

from agent_commerce.config import Mode, Protocol, Settings, get_settings

pytestmark = pytest.mark.testnet


def _has_testnet_credentials() -> bool:
    settings = get_settings()
    return (
        settings.mode is Mode.TESTNET
        and settings.buyer_private_key is not None
        and settings.seller_private_key is not None
    )


@pytest.mark.skipif(not _has_testnet_credentials(), reason="faltan credenciales de testnet AP2")
async def test_real_ap2_mandate_settles_on_base_sepolia() -> None:
    import asyncio
    import socket
    import threading

    import uvicorn
    from fastapi import FastAPI

    from agent_commerce.payments.factory import build_wallet_signer, get_payment_protocol

    settings = Settings(mode=Mode.TESTNET, protocol=Protocol.AP2)
    protocol = get_payment_protocol(settings)
    seller = build_wallet_signer(role="seller", settings=settings)
    buyer = build_wallet_signer(role="buyer", settings=settings)

    app = FastAPI()

    @app.post("/echo")
    async def echo(payload: dict) -> dict:
        return {"echo": payload}

    protocol.mount_seller(app, pay_to=seller.address, prices={"POST /echo": "$0.001"})

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        await asyncio.sleep(0.02)

    try:
        buyer_client = protocol.build_buyer_client(buyer)
        try:
            result = await buyer_client.request(
                "POST", f"http://127.0.0.1:{port}/echo", json={"hello": "testnet-ap2"}
            )
        finally:
            await buyer_client.aclose()

        assert result.status_code == 200
        assert result.receipt is not None
        assert result.receipt.settlement_id.startswith("pm_")
    finally:
        server.should_exit = True
