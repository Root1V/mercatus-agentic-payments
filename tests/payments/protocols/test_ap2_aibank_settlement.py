"""AP2 liquidado sobre el riel AIBank (RM-18: `Settings.ap2_settlement=aibank`
en vez de x402). Mismo mandato Cart/Payment que `test_ap2_protocol_mock.py`,
pero con `AIBankCredential` -- ese archivo verifica el riel x402 y no toca
ninguno de estos casos.

`AP2Protocol` mantiene un `MockAIBank` por instancia, así que vendedor y
comprador tienen que compartir la MISMA instancia de `AP2Protocol` para que
la autorización que arma el comprador sea visible al vendedor al redimir
(ver `payments/protocols/ap2_protocol.py`)."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from agent_commerce.config import Mode, Protocol, Settings, SettlementRail
from agent_commerce.payments.aibank_credential import AIBankCredential
from agent_commerce.payments.protocols.ap2_protocol import AP2Protocol


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


def _new_protocol() -> AP2Protocol:
    return AP2Protocol(Settings(mode=Mode.MOCK, protocol=Protocol.AP2, ap2_settlement=SettlementRail.AIBANK))


async def test_unpaid_request_returns_402_with_cart_mandate_offering_aibank() -> None:
    protocol = _new_protocol()
    app = _build_app(protocol, pay_to=AIBankCredential().account_id)
    port = _free_port()
    server = _run_app(app, port)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"http://127.0.0.1:{port}/echo", json={"hello": "world"})
        assert response.status_code == 402
        body = response.json()
        method_data = body["cartMandate"]["contents"]["payment_request"]["method_data"][0]
        assert method_data["supported_methods"] == "https://agent-commerce.dev/pay/aibank-transfer"
    finally:
        server.should_exit = True


async def test_paid_request_settles_via_aibank_and_returns_result() -> None:
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
        assert result.receipt.protocol == "ap2"
        assert result.receipt.payer == buyer.account_id
        assert result.receipt.pay_to == seller.account_id
        assert str(result.receipt.amount_usd) == "0.001"
        assert result.receipt.settlement_id.startswith("pm_")
    finally:
        server.should_exit = True


async def test_reusing_the_same_cart_mandate_twice_is_rejected() -> None:
    """Mismo anti-replay que el riel x402 (`test_ap2_protocol_mock.py`),
    ahora sobre AIBank."""
    protocol = _new_protocol()
    seller = AIBankCredential()
    buyer = AIBankCredential()
    app = _build_app(protocol, pay_to=seller.account_id)
    port = _free_port()
    server = _run_app(app, port)

    try:
        buyer_client = protocol.build_buyer_client(buyer)
        cart_response = await buyer_client._http.post(f"http://127.0.0.1:{port}/echo", json={"n": 1})
        assert cart_response.status_code == 402
        from ap2.types.mandate import CartMandate

        from agent_commerce.payments.protocols.ap2_protocol import _AP2_PAYMENT_MANDATE_HEADER

        cart_mandate = CartMandate.model_validate(cart_response.json()["cartMandate"])
        header_value = buyer_client._build_payment_mandate_header(cart_mandate)

        first = await buyer_client._http.post(
            f"http://127.0.0.1:{port}/echo", json={"n": 1}, headers={_AP2_PAYMENT_MANDATE_HEADER: header_value}
        )
        second = await buyer_client._http.post(
            f"http://127.0.0.1:{port}/echo", json={"n": 1}, headers={_AP2_PAYMENT_MANDATE_HEADER: header_value}
        )
        await buyer_client.aclose()

        assert first.status_code == 200
        assert second.status_code == 402
        assert "cart_already_redeemed" in second.json()["error"]
    finally:
        server.should_exit = True


async def test_wrong_api_key_for_a_known_account_is_rejected() -> None:
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
        finally:
            await buyer_client.aclose()
        assert first.status_code == 200

        impostor = AIBankCredential(account_id=buyer.account_id, api_key="wrong-key")
        impostor_client = protocol.build_buyer_client(impostor)
        try:
            with pytest.raises(Exception, match="invalid_credential"):
                await impostor_client.request("POST", f"http://127.0.0.1:{port}/echo", json={"n": 2})
        finally:
            await impostor_client.aclose()
    finally:
        server.should_exit = True
