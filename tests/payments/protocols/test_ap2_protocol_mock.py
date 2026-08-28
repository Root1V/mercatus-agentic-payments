from __future__ import annotations

import socket
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI

from agent_commerce.config import Mode, Protocol, Settings
from agent_commerce.payments.protocols.ap2_protocol import AP2Protocol
from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_app(protocol: AP2Protocol, pay_to: str) -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo_endpoint(payload: dict) -> dict:
        return {"echo": payload}

    protocol.mount_seller(app, pay_to=pay_to, prices={"POST /echo": "$0.001"})
    return app


def _run_app(app: FastAPI, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    return server


async def test_unpaid_request_returns_402_with_cart_mandate() -> None:
    settings = Settings(mode=Mode.MOCK, protocol=Protocol.AP2)
    protocol = AP2Protocol(settings)
    app = _build_app(protocol, pay_to=LocalEoaSigner().address)
    port = _free_port()
    server = _run_app(app, port)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"http://127.0.0.1:{port}/echo", json={"hello": "world"})
        assert response.status_code == 402
        body = response.json()
        assert "cartMandate" in body
        assert body["cartMandate"]["merchant_authorization"]
    finally:
        server.should_exit = True


async def test_paid_request_settles_via_x402_and_returns_result() -> None:
    settings = Settings(mode=Mode.MOCK, protocol=Protocol.AP2)
    protocol = AP2Protocol(settings)
    seller = LocalEoaSigner()
    buyer = LocalEoaSigner()
    app = _build_app(protocol, pay_to=seller.address)
    port = _free_port()
    server = _run_app(app, port)

    try:
        buyer_client = protocol.build_buyer_client(buyer)
        try:
            result = await buyer_client.request(
                "POST", f"http://127.0.0.1:{port}/echo", json={"hello": "world"}
            )
        finally:
            await buyer_client.aclose()

        assert result.status_code == 200
        assert result.json_body == {"echo": {"hello": "world"}}
        assert result.receipt is not None
        assert result.receipt.protocol == "ap2"
        assert result.receipt.payer.lower() == buyer.address.lower()
        assert result.receipt.pay_to.lower() == seller.address.lower()
        assert result.receipt.settlement_id.startswith("pm_")
    finally:
        server.should_exit = True


async def test_reusing_the_same_cart_mandate_twice_is_rejected() -> None:
    """Un cart_id ya redimido no debe poder liquidarse otra vez (anti-replay)."""
    settings = Settings(mode=Mode.MOCK, protocol=Protocol.AP2)
    protocol = AP2Protocol(settings)
    seller = LocalEoaSigner()
    buyer = LocalEoaSigner()
    app = _build_app(protocol, pay_to=seller.address)
    port = _free_port()
    server = _run_app(app, port)

    try:
        buyer_client = protocol.build_buyer_client(buyer)
        # Construimos el header de pago manualmente para poder reenviarlo dos veces.
        cart_response = await buyer_client._http.post(
            f"http://127.0.0.1:{port}/echo", json={"n": 1}
        )
        assert cart_response.status_code == 402
        from ap2.types.mandate import CartMandate

        from agent_commerce.payments.protocols.ap2_protocol import _AP2_PAYMENT_MANDATE_HEADER

        cart_mandate = CartMandate.model_validate(cart_response.json()["cartMandate"])
        header_value = buyer_client._build_payment_mandate_header(cart_mandate)

        first = await buyer_client._http.post(
            f"http://127.0.0.1:{port}/echo",
            json={"n": 1},
            headers={_AP2_PAYMENT_MANDATE_HEADER: header_value},
        )
        second = await buyer_client._http.post(
            f"http://127.0.0.1:{port}/echo",
            json={"n": 1},
            headers={_AP2_PAYMENT_MANDATE_HEADER: header_value},
        )
        await buyer_client.aclose()

        assert first.status_code == 200
        assert second.status_code == 402
        assert "cart_already_redeemed" in second.json()["error"]
    finally:
        server.should_exit = True
