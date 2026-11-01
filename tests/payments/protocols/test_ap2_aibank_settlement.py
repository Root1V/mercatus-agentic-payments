"""AP2 liquidado sobre el riel AIBank (RM-18: `Settings.ap2_settlement=aibank`
en vez de x402). Mismo mandato Cart/Payment que `test_ap2_protocol_mock.py`,
pero pagando desde una sub-cuenta (modelo A) o con un mandato (modelo B) --
ese archivo verifica el riel x402 y no toca ninguno de estos casos.

`AP2Protocol` mantiene un banco por instancia, así que vendedor y comprador
tienen que compartir la MISMA instancia de `AP2Protocol` para que la
autorización que arma el comprador sea visible al vendedor al redimir (ver
`payments/protocols/ap2_protocol.py`)."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from agent_commerce.config import Mode, Protocol, Settings, SettlementRail
from agent_commerce.payments.aibank_api import AIBankError
from agent_commerce.payments.aibank_credential import AIBankMandateCredential, AIBankSubAccount
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
    app = _build_app(protocol, pay_to=protocol.provision_aibank_account("seller").account_id)
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
    seller = protocol.provision_aibank_account("seller")
    buyer = protocol.provision_aibank_account("buyer")
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


async def test_reusing_the_same_cart_mandate_twice_is_rejected_and_charged_once() -> None:
    """Mismo anti-replay que el riel x402 (`test_ap2_protocol_mock.py`), ahora
    sobre AIBank -- y del lado del banco, la `Idempotency-Key` es el
    `cart_id`: armar el pago dos veces para el mismo carrito reencuentra la
    misma autorización en vez de cobrar dos veces."""
    protocol = _new_protocol()
    seller = protocol.provision_aibank_account("seller")
    buyer = protocol.provision_aibank_account("buyer")
    balance_before = protocol._mock_bank.available_balance(buyer.account_id)
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
        header_value = await buyer_client._build_payment_mandate_header(cart_mandate)
        await buyer_client._build_payment_mandate_header(cart_mandate)  # reintento del mismo carrito

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
        assert balance_before - protocol._mock_bank.available_balance(buyer.account_id) == 1000
    finally:
        server.should_exit = True


async def test_paid_request_settles_via_aibank_model_b_mandate() -> None:
    """Modelo B (`13-spec-modelos-a-y-b.md` §3): el comprador no paga desde
    una sub-cuenta nuestra -- trae un mandato que un titular ya aprobó sobre
    SU cuenta. El contrato de pago (`CartMandate`/`PaymentMandate`, recibo)
    es idéntico al del modelo A; lo único que cambia es la credencial."""
    protocol = _new_protocol()
    seller = protocol.provision_aibank_account("seller")
    app = _build_app(protocol, pay_to=seller.account_id)
    port = _free_port()
    server = _run_app(app, port)

    try:
        request = await protocol.aibank.create_consent_request(
            purpose="Pagos del agente de investigación de Acme S.A.", max_per_operation=1_000_000, max_total=10_000_000
        )
        holders = protocol.aibank_holder_channel
        holder = await holders.create_test_holder(name="Ana", initial_balance=50_000_000)
        await holders.approve(
            holder, request.handoff_code, account_id=holder.account_id, max_per_operation=1_000_000, max_total=10_000_000
        )
        # La cuenta del titular se aprende de la API de socio (`acc_`), no del
        # canal del titular (AE-06).
        approved = await protocol.aibank.get_consent_request(request.consent_request_id)
        assert approved.mandate_id is not None and approved.account_id is not None
        buyer = AIBankMandateCredential(mandate_id=approved.mandate_id, account_id=approved.account_id)

        buyer_client = protocol.build_buyer_client(buyer)
        try:
            result = await buyer_client.request(
                "POST", f"http://127.0.0.1:{port}/echo", json={"hello": "world"}
            )
        finally:
            await buyer_client.aclose()

        assert result.status_code == 200
        assert result.receipt is not None
        assert result.receipt.payer == approved.account_id
        assert result.receipt.pay_to == seller.account_id
        assert str(result.receipt.amount_usd) == "0.001"

        usage = await protocol.aibank.get_mandate(approved.mandate_id)
        assert usage.consumed == 1000
    finally:
        server.should_exit = True


async def test_paying_from_an_account_the_integration_never_opened_is_rejected() -> None:
    """Lo que reemplaza a "API key equivocada": en la API real no hay clave
    por cuenta (se autentica la integración), así que el equivalente es
    pagar desde una cuenta que esta integración no abrió -- `404
    account_not_found`, igual que una inexistente (doc 11, escenarios 12-13)."""
    protocol = _new_protocol()
    seller = protocol.provision_aibank_account("seller")
    app = _build_app(protocol, pay_to=seller.account_id)
    port = _free_port()
    server = _run_app(app, port)

    try:
        impostor = AIBankSubAccount(account_id="acc_" + "0" * 32)
        impostor_client = protocol.build_buyer_client(impostor)
        try:
            with pytest.raises(AIBankError, match="account_not_found"):
                await impostor_client.request("POST", f"http://127.0.0.1:{port}/echo", json={"n": 2})
        finally:
            await impostor_client.aclose()
    finally:
        server.should_exit = True
