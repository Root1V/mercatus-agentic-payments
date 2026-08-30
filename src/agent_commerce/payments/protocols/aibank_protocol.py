"""Adaptador de protocolo: AIBank, el riel de banco propio (RM-18).

A diferencia de x402/AP2 (rieles cripto: autorización vía firma EIP-712/
EIP-191 sobre una wallet EVM), AIBank es un riel bancario clásico:
autorizar + capturar contra la cuenta del agente en un banco (el nuestro,
"AIBank", o cualquiera que implemente el mismo contrato REST -- ver
`docs/roadmap.md` RM-18). No hay dirección EVM ni firma: la prueba de pago
es haber autenticado con éxito contra el banco con la API key de la cuenta.

Por eso este adaptador **no hereda `PaymentProtocol`**: esa ABC declara
`build_buyer_client(signer: WalletSigner)`, y forzar `AIBankCredential` en
ese molde (que exige `sign_typed_data`/`sign_message`) sería una
abstracción falsa -- exactamente lo que se decidió evitar al planificar
este riel (ver `docs/roadmap.md` RM-18: "no forzar una interfaz común").
`AIBankProtocol` implementa la misma forma por duck typing
(`name`, `mount_seller`, `build_buyer_client`) para que encaje donde hace
falta, con su propio tipo de credencial.

Transporte: mismo idioma HTTP 402 + reintento que x402/AP2 (402 con
`accepts`, header de prueba de pago en el reintento, header de liquidación
en la respuesta) -- así el descubrimiento del lado comprador no tiene que
aprender un mecanismo de transporte nuevo por riel, solo cambia qué hay
adentro del header.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
from x402.schemas.helpers import parse_money

from agent_commerce.config import Settings, get_settings

from .base import BuyerClient, PaidResponse, PaymentReceipt

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

    from agent_commerce.payments.aibank_credential import AIBankCredential

_PAYMENT_HEADER = "X-AIBANK-PAYMENT"
_SETTLEMENT_HEADER = "X-AIBANK-SETTLEMENT"
_NETWORK = "aibank:mock"


class AIBankProtocolError(Exception):
    pass


@dataclass
class _AIBankBuyerClient(BuyerClient):
    _http: httpx.AsyncClient
    _credential: AIBankCredential
    _bank: Any  # MockAIBank -- sin tipar el import fuerte acá, ver nota abajo

    async def request(
        self, method: str, url: str, *, json: dict[str, Any] | None = None
    ) -> PaidResponse:
        response = await self._http.request(method, url, json=json)
        if response.status_code != 402:
            return PaidResponse(
                status_code=response.status_code,
                json_body=response.json() if response.content else None,
                receipt=_receipt_from_headers(response.headers),
            )

        accepts = response.json()["accepts"]
        amount = Decimal(parse_money(accepts["price"])["amount"])

        authorization = self._bank.authorize(
            credential=self._credential,
            pay_to_account_id=accepts["payTo"],
            amount=amount,
            idempotency_key=uuid.uuid4().hex,
        )
        self._bank.capture(authorization_id=authorization.id, credential=self._credential)

        header_value = _encode_payment_header(
            authorization_id=authorization.id, payer_account_id=self._credential.account_id
        )

        paid_response = await self._http.request(
            method, url, json=json, headers={_PAYMENT_HEADER: header_value}
        )
        return PaidResponse(
            status_code=paid_response.status_code,
            json_body=paid_response.json() if paid_response.content else None,
            receipt=_receipt_from_headers(paid_response.headers),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def _encode_payment_header(*, authorization_id: str, payer_account_id: str) -> str:
    payload = {"authorization_id": authorization_id, "payer_account_id": payer_account_id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _receipt_from_headers(headers: Any) -> PaymentReceipt | None:
    header_value = headers.get(_SETTLEMENT_HEADER)
    if not header_value:
        return None
    raw = json.loads(base64.urlsafe_b64decode(header_value))
    return PaymentReceipt(
        protocol="aibank",
        network=_NETWORK,
        payer=raw["payer"],
        pay_to=raw["pay_to"],
        amount_usd=Decimal(raw["amount_usd"]),
        settlement_id=raw["authorization_id"],
        raw=raw,
    )


class _AIBankSellerState:
    def __init__(self, *, pay_to: str, prices: dict[str, str], bank: Any) -> None:
        self._pay_to = pay_to
        self._prices = prices
        self._bank = bank

    def route_key(self, method: str, path: str) -> str | None:
        candidate = f"{method} {path}"
        return candidate if candidate in self._prices else None

    def challenge(self, route_key: str) -> dict[str, Any]:
        return {
            "accepts": {
                "scheme": "aibank-transfer",
                "payTo": self._pay_to,
                "price": self._prices[route_key],
                "network": _NETWORK,
            }
        }

    def redeem(self, header_value: str, *, route_key: str) -> dict[str, Any]:
        try:
            raw = json.loads(base64.urlsafe_b64decode(header_value))
            authorization_id = raw["authorization_id"]
        except Exception as exc:
            raise AIBankProtocolError("malformed_payment_header") from exc

        authorization = self._bank.get(authorization_id)
        if authorization is None:
            raise AIBankProtocolError("authorization_not_found")
        if authorization.status != "captured":
            raise AIBankProtocolError(f"authorization_not_captured_status_{authorization.status}")
        if authorization.pay_to_account_id != self._pay_to:
            raise AIBankProtocolError("recipient_mismatch")

        expected_amount = Decimal(parse_money(self._prices[route_key])["amount"])
        if authorization.amount != expected_amount:
            raise AIBankProtocolError("amount_mismatch")

        return {
            "payer": authorization.payer_account_id,
            "pay_to": authorization.pay_to_account_id,
            "amount_usd": str(authorization.amount),
            "authorization_id": authorization.id,
        }


class AIBankProtocol:
    """Adaptador de protocolo AIBank -- ver docstring del módulo sobre por
    qué no hereda `PaymentProtocol`."""

    name = "aibank"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        from agent_commerce.payments.mock_aibank import MockAIBank

        # Un único banco en memoria por instancia de protocolo, compartido
        # entre vendedor y comprador (mismo criterio que `_facilitator` en
        # X402Protocol/AP2Protocol) -- no existe todavía un AIBank real
        # contra el cual hablar en modo testnet (ver docstring del módulo).
        self._bank = MockAIBank()

    def mount_seller(self, app: FastAPI, *, pay_to: str, prices: dict[str, str]) -> None:
        from fastapi.responses import JSONResponse

        state = _AIBankSellerState(pay_to=pay_to, prices=prices, bank=self._bank)

        @app.middleware("http")
        async def _aibank_payment_middleware(request: Request, call_next: Any) -> Any:
            route_key = state.route_key(request.method, request.url.path)
            if route_key is None:
                return await call_next(request)

            header_value = request.headers.get(_PAYMENT_HEADER)
            if not header_value:
                return JSONResponse(status_code=402, content=state.challenge(route_key))

            try:
                settlement = state.redeem(header_value, route_key=route_key)
            except AIBankProtocolError as exc:
                return JSONResponse(status_code=402, content={"error": str(exc)})

            response = await call_next(request)
            response.headers[_SETTLEMENT_HEADER] = base64.urlsafe_b64encode(
                json.dumps(settlement).encode()
            ).decode()
            return response

    def build_buyer_client(self, credential: AIBankCredential) -> BuyerClient:
        return _AIBankBuyerClient(httpx.AsyncClient(), credential, self._bank)
