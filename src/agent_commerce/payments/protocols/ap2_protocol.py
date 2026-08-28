"""Adaptador de protocolo: AP2 (Agent Payments Protocol, de Google).

A diferencia de x402 (liquidación cripto directa), AP2 es un protocolo de
**autorización**: encadena tres mandatos firmados -- `IntentMandate` (el
usuario delega autoridad), `CartMandate` (el comerciante firma un carrito a
un precio concreto) y `PaymentMandate` (el comprador autoriza el pago de
ese carrito) -- agnósticos al riel de pago real. Este módulo usa los tipos
pydantic reales del paquete `ap2` (que reflejan 1:1 los tipos oficiales de
`google-agentic-commerce/AP2`) para esos mandatos, y liquida el dinero
delegando en el mismo motor x402 que usa `X402Protocol`
(`payments.facilitator_selection`) -- tal como en el mundo real la
extensión oficial `a2a-x402` de Google usa x402 como riel de liquidación
dentro de un mandato AP2.

Simplificaciones deliberadas de esta implementación de referencia (ver
`docs/roadmap.md` RM-02 y `docs/business_model_analysis.md`):

- El transporte es HTTP 402 + reintento (como x402), no el transporte A2A
  oficial de Google (JSON-RPC/gRPC sobre "Agent Cards"). Esto evita la
  dependencia pesada de `google-adk`/`a2a-sdk` y permite que este framework
  comparta un único mecanismo de descubrimiento entre ambos protocolos.
- `CartMandate.merchant_authorization` y `PaymentMandate.user_authorization`
  son una firma EIP-191 (`personal_sign`) codificada en base64url sobre el
  JSON canónico del contenido, no un JWT real firmado con una PKI de
  comercio -- la garantía criptográfica (no repudio, integridad) es
  equivalente para los fines de este framework, pero no es el formato JWT
  exacto que describe la especificación.
- No se implementa el `IntentMandate` humano-presente (confirmación de
  carrito por un usuario real): el flujo es agente-a-agente autónomo de
  punta a punta, como pide el caso de uso de este framework.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
from ap2.types.mandate import (
    CartContents,
    CartMandate,
    PaymentMandate,
    PaymentMandateContents,
)
from ap2.types.payment_request import (
    PaymentCurrencyAmount,
    PaymentDetailsInit,
    PaymentItem,
    PaymentMethodData,
    PaymentRequest,
    PaymentResponse,
)
from eth_account import Account
from eth_account.messages import encode_defunct
from x402 import PaymentPayload, PaymentRequirements, SettleResponse
from x402.mechanisms.evm.default_assets import DEFAULT_ASSETS
from x402.mechanisms.evm.exact.client import ExactEvmScheme as ExactEvmClientScheme
from x402.mechanisms.evm.types import ExactEIP3009Payload
from x402.schemas.helpers import convert_to_token_amount, parse_money

from agent_commerce.config import Settings, get_settings
from agent_commerce.payments.facilitator_selection import build_facilitator_client
from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner

from .base import BuyerClient, PaidResponse, PaymentProtocol, PaymentReceipt

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

    from agent_commerce.payments.wallets.base import WalletSigner

_AP2_PAYMENT_MANDATE_HEADER = "X-AP2-PAYMENT-MANDATE"
_AP2_SETTLEMENT_HEADER = "X-AP2-SETTLEMENT"
_X402_METHOD_NAME = "https://agent-commerce.dev/pay/x402-usdc"
_CART_TTL_SECONDS = 900
_USDC_ATOMIC_UNITS = Decimal(10**6)


class AP2Error(Exception):
    pass


def _canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def _iso_expiry(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _build_requirements(*, network: str, pay_to: str, price_usd: str) -> PaymentRequirements:
    assets = DEFAULT_ASSETS.get(network)
    if not assets:
        raise AP2Error(f"Sin USDC por defecto configurado para la red {network}")
    asset = assets[0]
    parsed = parse_money(price_usd)
    amount = convert_to_token_amount(parsed["amount"], asset["decimals"])
    return PaymentRequirements(
        scheme="exact",
        network=network,
        asset=asset["asset"],
        amount=amount,
        pay_to=pay_to,
        max_timeout_seconds=_CART_TTL_SECONDS,
        extra={"name": asset["name"], "version": asset["version"]},
    )


def _build_cart_mandate(
    *,
    requirements: PaymentRequirements,
    cart_id: str,
    price_usd: str,
    description: str,
    merchant_name: str,
    merchant_signer: WalletSigner,
) -> CartMandate:
    parsed = parse_money(price_usd)
    total_item = PaymentItem(
        label=description, amount=PaymentCurrencyAmount(currency="USD", value=float(parsed["amount"]))
    )
    method_data = PaymentMethodData(
        supported_methods=_X402_METHOD_NAME,
        data={
            "network": str(requirements.network),
            "payTo": requirements.pay_to,
            "asset": requirements.asset,
            "amount": requirements.amount,
            "assetName": requirements.extra["name"],
            "assetVersion": requirements.extra["version"],
            "maxTimeoutSeconds": requirements.max_timeout_seconds,
        },
    )
    contents = CartContents(
        id=cart_id,
        user_cart_confirmation_required=False,
        payment_request=PaymentRequest(
            method_data=[method_data],
            details=PaymentDetailsInit(id=cart_id, display_items=[total_item], total=total_item),
        ),
        cart_expiry=_iso_expiry(_CART_TTL_SECONDS),
        merchant_name=merchant_name,
    )
    signature = merchant_signer.sign_message(_canonical_json(contents.model_dump(mode="json")))
    return CartMandate(
        contents=contents, merchant_authorization=base64.urlsafe_b64encode(signature).decode()
    )


@dataclass
class _PendingCart:
    requirements: PaymentRequirements
    expires_at: float


class _AP2SellerState:
    def __init__(
        self,
        *,
        network: str,
        pay_to: str,
        prices: dict[str, str],
        merchant_signer: WalletSigner,
        merchant_name: str,
        facilitator: Any,
    ) -> None:
        self._network = network
        self._pay_to = pay_to
        self._prices = prices
        self._merchant_signer = merchant_signer
        self._merchant_name = merchant_name
        self._facilitator = facilitator
        self._pending_carts: dict[str, _PendingCart] = {}
        self._used_cart_ids: set[str] = set()

    def route_key(self, method: str, path: str) -> str | None:
        candidate = f"{method} {path}"
        return candidate if candidate in self._prices else None

    def issue_cart(self, route_key: str) -> CartMandate:
        price = self._prices[route_key]
        cart_id = f"cart_{uuid.uuid4().hex}"
        requirements = _build_requirements(network=self._network, pay_to=self._pay_to, price_usd=price)
        cart_mandate = _build_cart_mandate(
            requirements=requirements,
            cart_id=cart_id,
            price_usd=price,
            description=route_key,
            merchant_name=self._merchant_name,
            merchant_signer=self._merchant_signer,
        )
        self._pending_carts[cart_id] = _PendingCart(
            requirements=requirements, expires_at=time.time() + _CART_TTL_SECONDS
        )
        return cart_mandate

    async def redeem(self, header_value: str) -> tuple[SettleResponse, str]:
        try:
            raw = json.loads(base64.urlsafe_b64decode(header_value))
            payment_mandate = PaymentMandate.model_validate(raw)
        except Exception as exc:
            raise AP2Error("malformed_payment_mandate") from exc

        contents = payment_mandate.payment_mandate_contents
        cart_id = contents.payment_details_id
        pending = self._pending_carts.get(cart_id)
        if pending is None:
            raise AP2Error("cart_not_found")
        if cart_id in self._used_cart_ids:
            raise AP2Error("cart_already_redeemed")
        if time.time() > pending.expires_at:
            raise AP2Error("cart_expired")

        x402_payload_dict = (contents.payment_response.details or {}).get("x402Payload")
        if not x402_payload_dict:
            raise AP2Error("missing_x402_payload")
        payment_payload = PaymentPayload.model_validate(x402_payload_dict)
        evm_payload = ExactEIP3009Payload.from_dict(payment_payload.payload)
        payer = evm_payload.authorization.from_address

        if not payment_mandate.user_authorization:
            raise AP2Error("missing_user_authorization")
        contents_bytes = _canonical_json(contents.model_dump(mode="json"))
        try:
            signature = base64.urlsafe_b64decode(payment_mandate.user_authorization)
            recovered = Account.recover_message(
                encode_defunct(primitive=contents_bytes), signature=signature
            )
        except Exception as exc:
            raise AP2Error("invalid_mandate_signature") from exc
        if recovered.lower() != payer.lower():
            raise AP2Error("mandate_signature_does_not_match_payer")

        settle_response = await self._facilitator.settle(payment_payload, pending.requirements)
        if not settle_response.success:
            raise AP2Error(f"settlement_failed:{settle_response.error_reason}")

        self._used_cart_ids.add(cart_id)
        return settle_response, contents.payment_mandate_id


@dataclass
class _AP2BuyerClient(BuyerClient):
    _http: httpx.AsyncClient
    _signer: WalletSigner
    _scheme: ExactEvmClientScheme

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

        cart_mandate = CartMandate.model_validate(response.json()["cartMandate"])
        header_value = self._build_payment_mandate_header(cart_mandate)

        paid_response = await self._http.request(
            method, url, json=json, headers={_AP2_PAYMENT_MANDATE_HEADER: header_value}
        )
        return PaidResponse(
            status_code=paid_response.status_code,
            json_body=paid_response.json() if paid_response.content else None,
            receipt=_receipt_from_headers(paid_response.headers),
        )

    def _build_payment_mandate_header(self, cart_mandate: CartMandate) -> str:
        method_data = cart_mandate.contents.payment_request.method_data[0]
        pay_data = method_data.data or {}
        requirements = PaymentRequirements(
            scheme="exact",
            network=pay_data["network"],
            asset=pay_data["asset"],
            amount=pay_data["amount"],
            pay_to=pay_data["payTo"],
            max_timeout_seconds=pay_data.get("maxTimeoutSeconds", _CART_TTL_SECONDS),
            extra={"name": pay_data["assetName"], "version": pay_data["assetVersion"]},
        )
        inner_payload = self._scheme.create_payment_payload(requirements)
        payment_payload = PaymentPayload(payload=inner_payload, accepted=requirements)

        contents = PaymentMandateContents(
            payment_mandate_id=f"pm_{uuid.uuid4().hex}",
            payment_details_id=cart_mandate.contents.id,
            payment_details_total=cart_mandate.contents.payment_request.details.total,
            payment_response=PaymentResponse(
                request_id=cart_mandate.contents.id,
                method_name=_X402_METHOD_NAME,
                details={"x402Payload": payment_payload.model_dump(mode="json")},
            ),
            merchant_agent=cart_mandate.contents.merchant_name,
        )
        contents_bytes = _canonical_json(contents.model_dump(mode="json"))
        signature = self._signer.sign_message(contents_bytes)
        mandate = PaymentMandate(
            payment_mandate_contents=contents,
            user_authorization=base64.urlsafe_b64encode(signature).decode(),
        )
        return base64.urlsafe_b64encode(_canonical_json(mandate.model_dump(mode="json"))).decode()

    async def aclose(self) -> None:
        await self._http.aclose()


def _receipt_from_headers(headers: Any) -> PaymentReceipt | None:
    header_value = headers.get(_AP2_SETTLEMENT_HEADER)
    if not header_value:
        return None
    raw = json.loads(base64.urlsafe_b64decode(header_value))
    settle = raw["settle"]
    amount_usd = Decimal(settle["amount"]) / _USDC_ATOMIC_UNITS if settle.get("amount") else Decimal(0)
    return PaymentReceipt(
        protocol="ap2",
        network=str(settle["network"]),
        payer=settle.get("payer") or "",
        pay_to=raw.get("pay_to", ""),
        amount_usd=amount_usd,
        settlement_id=raw.get("payment_mandate_id") or settle.get("transaction", ""),
        raw=raw,
    )


class AP2Protocol(PaymentProtocol):
    name = "ap2"

    def __init__(self, settings: Settings | None = None, *, merchant_name: str = "agent_commerce demo") -> None:
        self._settings = settings or get_settings()
        self._merchant_name = merchant_name
        # Clave de identidad del comerciante para firmar CartMandate -- distinta,
        # a propósito, de `pay_to` (la dirección que RECIBE los fondos):
        # en el mundo real la identidad de firma y la wallet de cobro no
        # tienen por qué ser la misma clave.
        self._merchant_signer = LocalEoaSigner()
        self._facilitator = build_facilitator_client(self._settings)

    def mount_seller(self, app: FastAPI, *, pay_to: str, prices: dict[str, str]) -> None:
        from fastapi.responses import JSONResponse

        state = _AP2SellerState(
            network=self._settings.network,
            pay_to=pay_to,
            prices=prices,
            merchant_signer=self._merchant_signer,
            merchant_name=self._merchant_name,
            facilitator=self._facilitator,
        )

        @app.middleware("http")
        async def _ap2_payment_middleware(request: Request, call_next: Any) -> Any:
            route_key = state.route_key(request.method, request.url.path)
            if route_key is None:
                return await call_next(request)

            header_value = request.headers.get(_AP2_PAYMENT_MANDATE_HEADER)
            if not header_value:
                cart_mandate = state.issue_cart(route_key)
                return JSONResponse(
                    status_code=402,
                    content={"cartMandate": cart_mandate.model_dump(mode="json")},
                )

            try:
                settle_response, payment_mandate_id = await state.redeem(header_value)
            except AP2Error as exc:
                return JSONResponse(status_code=402, content={"error": str(exc)})

            response = await call_next(request)
            payload = {
                "settle": settle_response.model_dump(mode="json"),
                "pay_to": pay_to,
                "payment_mandate_id": payment_mandate_id,
            }
            response.headers[_AP2_SETTLEMENT_HEADER] = base64.urlsafe_b64encode(
                _canonical_json(payload)
            ).decode()
            return response

    def build_buyer_client(self, signer: WalletSigner) -> BuyerClient:
        scheme = ExactEvmClientScheme(signer)
        return _AP2BuyerClient(httpx.AsyncClient(), signer, scheme)
