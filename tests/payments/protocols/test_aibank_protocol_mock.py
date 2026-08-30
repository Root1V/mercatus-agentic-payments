"""AIBank (RM-18) no comparte el fixture parametrizado `seller_server`
(`tests/conftest.py`, `params=[Protocol.X402, Protocol.AP2]`) a propósito:
ese fixture -- y `test_protocol_contract.py` -- asumen un `WalletSigner`
como credencial de comprador para cualquier protocolo, cosa que AIBank no
tiene (ver `payments/protocols/aibank_protocol.py`). Este archivo mirror-ea
la estructura de `test_x402_protocol_mock.py` pero con `AIBankCredential`."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from agent_commerce.config import Mode, Protocol, Settings
from agent_commerce.payments.aibank_credential import AIBankCredential
from agent_commerce.payments.protocols.aibank_protocol import AIBankProtocol


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_app(protocol: AIBankProtocol, pay_to: str) -> FastAPI:
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


def _new_protocol() -> AIBankProtocol:
    return AIBankProtocol(Settings(mode=Mode.MOCK, protocol=Protocol.AIBANK))


async def test_unpaid_request_returns_402() -> None:
    protocol = _new_protocol()
    app = _build_app(protocol, pay_to=AIBankCredential().account_id)
    port = _free_port()
    server = _run_app(app, port)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"http://127.0.0.1:{port}/echo", json={"hello": "world"})
        assert response.status_code == 402
        assert response.json()["accepts"]["scheme"] == "aibank-transfer"
    finally:
        server.should_exit = True


async def test_paid_request_settles_and_returns_result() -> None:
    protocol = _new_protocol()
    seller = AIBankCredential()
    buyer = AIBankCredential()
    app = _build_app(protocol, pay_to=seller.account_id)
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
        assert result.receipt.protocol == "aibank"
        assert result.receipt.payer == buyer.account_id
        assert result.receipt.pay_to == seller.account_id
        assert str(result.receipt.amount_usd) == "0.001"
        assert result.receipt.settlement_id.startswith("auth_")
    finally:
        server.should_exit = True


async def test_wrong_api_key_for_a_known_account_is_rejected() -> None:
    """La cuenta queda "abierta" (trust-on-first-use) en la primera llamada
    -- un segundo intento con el mismo account_id pero otro api_key tiene
    que fallar, probando que el chequeo de credencial es real."""
    protocol = _new_protocol()
    seller = AIBankCredential()
    buyer = AIBankCredential()
    app = _build_app(protocol, pay_to=seller.account_id)
    port = _free_port()
    server = _run_app(app, port)

    try:
        buyer_client = protocol.build_buyer_client(buyer)
        try:
            first = await buyer_client.request(
                "POST", f"http://127.0.0.1:{port}/echo", json={"n": 1}
            )
        finally:
            await buyer_client.aclose()
        assert first.status_code == 200

        impostor = AIBankCredential(account_id=buyer.account_id, api_key="wrong-key")
        impostor_client = protocol.build_buyer_client(impostor)
        try:
            with pytest.raises(Exception, match="invalid_credential"):
                await impostor_client.request(
                    "POST", f"http://127.0.0.1:{port}/echo", json={"n": 2}
                )
        finally:
            await impostor_client.aclose()
    finally:
        server.should_exit = True


async def test_each_call_authorizes_and_captures_independently() -> None:
    protocol = _new_protocol()
    seller = AIBankCredential()
    buyer = AIBankCredential()
    app = _build_app(protocol, pay_to=seller.account_id)
    port = _free_port()
    server = _run_app(app, port)

    try:
        buyer_client = protocol.build_buyer_client(buyer)
        try:
            first = await buyer_client.request("POST", f"http://127.0.0.1:{port}/echo", json={"n": 1})
            second = await buyer_client.request("POST", f"http://127.0.0.1:{port}/echo", json={"n": 2})
        finally:
            await buyer_client.aclose()

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.receipt.settlement_id != second.receipt.settlement_id
    finally:
        server.should_exit = True
