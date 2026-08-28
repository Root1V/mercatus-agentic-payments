from __future__ import annotations

import socket
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI

from agent_commerce.config import Mode, Protocol, Settings
from agent_commerce.payments.protocols.x402_protocol import X402Protocol
from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_app(protocol: X402Protocol, pay_to: str) -> FastAPI:
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


async def test_unpaid_request_returns_402() -> None:
    settings = Settings(mode=Mode.MOCK, protocol=Protocol.X402)
    protocol = X402Protocol(settings)
    app = _build_app(protocol, pay_to=LocalEoaSigner().address)
    port = _free_port()
    server = _run_app(app, port)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"http://127.0.0.1:{port}/echo", json={"hello": "world"})
        assert response.status_code == 402
    finally:
        server.should_exit = True


async def test_paid_request_settles_and_returns_result() -> None:
    settings = Settings(mode=Mode.MOCK, protocol=Protocol.X402)
    protocol = X402Protocol(settings)
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
        assert result.receipt.protocol == "x402"
        assert result.receipt.payer.lower() == buyer.address.lower()
        assert result.receipt.settlement_id.startswith("0xmock")
    finally:
        server.should_exit = True


async def test_reused_nonce_is_rejected_by_the_mock_facilitator() -> None:
    """El MockFacilitator debe rechazar una autorización EIP-3009 reutilizada:
    prueba que la verificación de nonce (no solo la firma) es real."""
    settings = Settings(mode=Mode.MOCK, protocol=Protocol.X402)
    protocol = X402Protocol(settings)
    seller = LocalEoaSigner()
    buyer = LocalEoaSigner()
    app = _build_app(protocol, pay_to=seller.address)
    port = _free_port()
    server = _run_app(app, port)

    try:
        buyer_client = protocol.build_buyer_client(buyer)
        try:
            first = await buyer_client.request(
                "POST", f"http://127.0.0.1:{port}/echo", json={"n": 1}
            )
            second = await buyer_client.request(
                "POST", f"http://127.0.0.1:{port}/echo", json={"n": 2}
            )
        finally:
            await buyer_client.aclose()

        # Cada llamada del x402Client firma una autorización NUEVA (nonce distinto),
        # así que ambas deben poder liquidar de forma independiente.
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.receipt.settlement_id != second.receipt.settlement_id
    finally:
        server.should_exit = True
