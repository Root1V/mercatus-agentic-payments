"""Adaptador de protocolo: AP2 (Agent Payments Protocol, de Google).

A diferencia de x402 (liquidación cripto directa), AP2 es un protocolo de
**autorización**: encadena tres mandatos firmados -- `IntentMandate` (el
usuario delega autoridad), `CartMandate` (el comerciante firma un carrito a
un precio concreto) y `PaymentMandate` (el comprador autoriza el pago de
ese carrito) -- agnósticos al riel de pago real. Este módulo usa los tipos
pydantic reales del paquete `ap2` (que reflejan 1:1 los tipos oficiales de
`google-agentic-commerce/AP2`) para esos mandatos.

**Riel de liquidación (RM-18)**: AP2 está diseñado a propósito para ser
agnóstico al riel real de pago -- por eso acá `AIBankCredential`/
`MockAIBank` (banco propio, RM-18) se conectan como un **segundo riel de
liquidación de AP2**, no como un protocolo aparte. El riel x402 liquida
delegando en el mismo motor x402 que usa `X402Protocol` (tal como en el
mundo real la extensión oficial `a2a-x402` de Google usa x402 como riel de
liquidación dentro de un mandato AP2); el riel AIBank liquida autorizando +
capturando contra `MockAIBank` en vez de firmar una transferencia on-chain.
Pedirle a un banco que "hable x402" directamente no tiene sentido: lo
obligaría a custodiar cripto y firmar EIP-712 como una wallet -- en ese
punto ya sería Circle (RM-06), no un banco propio.

`__init__` construye SIEMPRE el facilitator de x402 y el `MockAIBank`,
sin importar `Settings.ap2_settlement` -- ese campo es solo el riel por
defecto que usan el comprador (`build_buyer_client`, que en realidad decide
por el TIPO de credencial que recibe) y el vendedor cuando nadie pide
explícitamente otra cosa (CLI/ejemplos/tests, un único riel fijo por
proceso, como cualquier otra `Settings`). El dashboard (RM-19) en cambio le
pasa a `mount_seller` su propio `rail_resolver` -- una función que lee en
cada request cuál es el backend de wallet configurado ahora mismo -- así
que ahí el riel de AP2 se puede cambiar en caliente sin reiniciar el
proceso, igual que el resto de la configuración del comprador.

La firma del `CartMandate` (`merchant_authorization`, identidad del
comerciante) es independiente del riel y siempre EIP-191 vía
`LocalEoaSigner`, sea cual sea el riel de liquidación -- afirmar "soy este
comerciante" no depende de cómo se cobra. La firma del `PaymentMandate`
(`user_authorization`, consentimiento del comprador) SÍ depende del riel:
con x402 es una firma EIP-191 real sobre el contenido exacto del mandato;
con AIBank no existe firma en ese modelo (ver `aibank_credential.py`), así
que la garantía de no-repudio la da haber autorizado+capturado con éxito
contra el banco (el vendedor lo verifica de vuelta contra `MockAIBank` en
`redeem`, igual que con x402 verifica contra el facilitator) -- una
simplificación real y documentada, no un descuido: no hay firma que ate esa
autorización bancaria al contenido exacto de ESE mandato en particular,
solo que el `authorization_id` sea de un solo uso y que pay_to/amount
coincidan con lo que el banco realmente registró.

Otras simplificaciones deliberadas de esta implementación de referencia (ver
`docs/roadmap.md` RM-02 y `docs/business_model_analysis.md`):

- El transporte es HTTP 402 + reintento (como x402), no el transporte A2A
  oficial de Google (JSON-RPC/gRPC sobre "Agent Cards"). Esto evita la
  dependencia pesada de `google-adk`/`a2a-sdk` y permite que este framework
  comparta un único mecanismo de descubrimiento entre ambos protocolos.
- `CartMandate.merchant_authorization` y `PaymentMandate.user_authorization`
  (riel x402) son una firma EIP-191 (`personal_sign`) codificada en
  base64url sobre el JSON canónico del contenido, no un JWT real firmado
  con una PKI de comercio -- la garantía criptográfica (no repudio,
  integridad) es equivalente para los fines de este framework, pero no es
  el formato JWT exacto que describe la especificación.
- No se implementa el `IntentMandate` humano-presente (confirmación de
  carrito por un usuario real): el flujo es agente-a-agente autónomo de
  punta a punta, como pide el caso de uso de este framework.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import Callable
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

from agent_commerce.config import Settings, SettlementRail, get_settings
from agent_commerce.payments.aibank_credential import AIBankCredential
from agent_commerce.payments.facilitator_selection import build_facilitator_client
from agent_commerce.payments.wallets.base import WalletSigner
from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner

from .base import BuyerClient, PaidResponse, PaymentProtocol, PaymentReceipt

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

    from agent_commerce.payments.mock_aibank import MockAIBank
    from agent_commerce.payments.protocols.base import PayerCredential

_AP2_PAYMENT_MANDATE_HEADER = "X-AP2-PAYMENT-MANDATE"
_AP2_SETTLEMENT_HEADER = "X-AP2-SETTLEMENT"
_X402_METHOD_NAME = "https://agent-commerce.dev/pay/x402-usdc"
_AIBANK_METHOD_NAME = "https://agent-commerce.dev/pay/aibank-transfer"
_AIBANK_NETWORK = "aibank:mock"
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


def _x402_method_data(requirements: PaymentRequirements) -> PaymentMethodData:
    return PaymentMethodData(
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


def _aibank_method_data(*, pay_to: str, price_usd: str) -> PaymentMethodData:
    return PaymentMethodData(
        supported_methods=_AIBANK_METHOD_NAME,
        data={"payTo": pay_to, "price": price_usd, "network": _AIBANK_NETWORK},
    )


def _build_cart_mandate(
    *,
    cart_id: str,
    price_usd: str,
    description: str,
    merchant_name: str,
    merchant_signer: WalletSigner,
    method_data: PaymentMethodData,
) -> CartMandate:
    parsed = parse_money(price_usd)
    total_item = PaymentItem(
        label=description, amount=PaymentCurrencyAmount(currency="USD", value=float(parsed["amount"]))
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
    rail: SettlementRail
    pay_to: str
    amount: Decimal
    expires_at: float
    x402_requirements: PaymentRequirements | None = None  # solo rail=x402


class _AP2SellerState:
    def __init__(
        self,
        *,
        network: str,
        pay_to: str,
        prices: dict[str, str],
        merchant_signer: WalletSigner,
        merchant_name: str,
        rail_resolver: Callable[[], SettlementRail],
        aibank_pay_to: str | None = None,
        facilitator: Any = None,
        bank: MockAIBank | None = None,
    ) -> None:
        self._network = network
        self._pay_to = pay_to
        self._aibank_pay_to = aibank_pay_to
        self._prices = prices
        self._merchant_signer = merchant_signer
        self._merchant_name = merchant_name
        self._rail_resolver = rail_resolver
        self._facilitator = facilitator
        self._bank = bank
        self._pending_carts: dict[str, _PendingCart] = {}
        self._used_cart_ids: set[str] = set()

    def route_key(self, method: str, path: str) -> str | None:
        candidate = f"{method} {path}"
        return candidate if candidate in self._prices else None

    def issue_cart(self, route_key: str) -> CartMandate:
        # El riel se resuelve DE NUEVO en cada carrito emitido (no una vez al
        # montar el vendedor): así, en el dashboard, cambiar el backend de
        # wallet del comprador (RM-19) cambia con qué riel el vendedor
        # empieza a ofrecer el próximo pago, sin reiniciar el proceso. Un
        # carrito ya emitido conserva SU riel (guardado en `_PendingCart`)
        # aunque la config cambie antes de que se redima -- evita que un
        # cambio a mitad de camino invalide un pago en curso.
        rail = self._rail_resolver()
        price = self._prices[route_key]
        cart_id = f"cart_{uuid.uuid4().hex}"
        amount = Decimal(parse_money(price)["amount"])

        if rail is SettlementRail.X402:
            requirements = _build_requirements(network=self._network, pay_to=self._pay_to, price_usd=price)
            method_data = _x402_method_data(requirements)
            pending = _PendingCart(
                rail=rail,
                pay_to=self._pay_to,
                amount=amount,
                expires_at=time.time() + _CART_TTL_SECONDS,
                x402_requirements=requirements,
            )
        else:
            assert self._aibank_pay_to is not None
            method_data = _aibank_method_data(pay_to=self._aibank_pay_to, price_usd=price)
            pending = _PendingCart(
                rail=rail,
                pay_to=self._aibank_pay_to,
                amount=amount,
                expires_at=time.time() + _CART_TTL_SECONDS,
            )

        cart_mandate = _build_cart_mandate(
            cart_id=cart_id,
            price_usd=price,
            description=route_key,
            merchant_name=self._merchant_name,
            merchant_signer=self._merchant_signer,
            method_data=method_data,
        )
        self._pending_carts[cart_id] = pending
        return cart_mandate

    async def redeem(self, header_value: str) -> tuple[dict[str, Any], str]:
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
        if not payment_mandate.user_authorization:
            raise AP2Error("missing_user_authorization")

        if pending.rail is SettlementRail.X402:
            settle = await self._redeem_x402(
                contents=contents, pending=pending, user_authorization=payment_mandate.user_authorization
            )
        else:
            settle = self._redeem_aibank(contents=contents, pending=pending)

        self._used_cart_ids.add(cart_id)
        return settle, contents.payment_mandate_id

    async def _redeem_x402(
        self, *, contents: Any, pending: _PendingCart, user_authorization: str
    ) -> dict[str, Any]:
        x402_payload_dict = (contents.payment_response.details or {}).get("x402Payload")
        if not x402_payload_dict:
            raise AP2Error("missing_x402_payload")
        payment_payload = PaymentPayload.model_validate(x402_payload_dict)
        evm_payload = ExactEIP3009Payload.from_dict(payment_payload.payload)
        payer = evm_payload.authorization.from_address

        contents_bytes = _canonical_json(contents.model_dump(mode="json"))
        try:
            signature = base64.urlsafe_b64decode(user_authorization)
            recovered = Account.recover_message(
                encode_defunct(primitive=contents_bytes), signature=signature
            )
        except Exception as exc:
            raise AP2Error("invalid_mandate_signature") from exc
        if recovered.lower() != payer.lower():
            raise AP2Error("mandate_signature_does_not_match_payer")

        assert self._facilitator is not None
        assert pending.x402_requirements is not None
        settle_response: SettleResponse = await self._facilitator.settle(
            payment_payload, pending.x402_requirements
        )
        if not settle_response.success:
            raise AP2Error(f"settlement_failed:{settle_response.error_reason}")

        amount_usd = (
            Decimal(settle_response.amount) / _USDC_ATOMIC_UNITS
            if settle_response.amount is not None
            else Decimal(0)
        )
        return {
            "payer": settle_response.payer or "",
            "pay_to": pending.pay_to,
            "network": str(settle_response.network),
            "amount": str(amount_usd),
            "transaction": settle_response.transaction,
        }

    def _redeem_aibank(self, *, contents: Any, pending: _PendingCart) -> dict[str, Any]:
        aibank_payload = (contents.payment_response.details or {}).get("aibankPayload")
        if not aibank_payload:
            raise AP2Error("missing_aibank_payload")

        assert self._bank is not None
        authorization = self._bank.get(aibank_payload.get("authorization_id"))
        if authorization is None:
            raise AP2Error("aibank_authorization_not_found")
        if authorization.status != "captured":
            raise AP2Error(f"aibank_authorization_not_captured_status_{authorization.status}")
        if authorization.pay_to_account_id != pending.pay_to:
            raise AP2Error("aibank_recipient_mismatch")
        if authorization.amount != pending.amount:
            raise AP2Error("aibank_amount_mismatch")

        return {
            "payer": authorization.payer_account_id,
            "pay_to": pending.pay_to,
            "network": _AIBANK_NETWORK,
            "amount": str(authorization.amount),
            "transaction": authorization.id,
        }


@dataclass
class _AP2BuyerClient(BuyerClient):
    _http: httpx.AsyncClient
    _credential: PayerCredential
    _rail: SettlementRail
    _scheme: ExactEvmClientScheme | None = None  # solo rail=x402
    _bank: MockAIBank | None = None  # solo rail=aibank

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

        if self._rail is SettlementRail.X402:
            details, user_authorization = self._pay_x402(pay_data)
        else:
            details, user_authorization = self._pay_aibank(pay_data)

        contents = PaymentMandateContents(
            payment_mandate_id=f"pm_{uuid.uuid4().hex}",
            payment_details_id=cart_mandate.contents.id,
            payment_details_total=cart_mandate.contents.payment_request.details.total,
            payment_response=PaymentResponse(
                request_id=cart_mandate.contents.id,
                method_name=method_data.supported_methods,
                details=details,
            ),
            merchant_agent=cart_mandate.contents.merchant_name,
        )
        contents_bytes = _canonical_json(contents.model_dump(mode="json"))

        if self._rail is SettlementRail.X402:
            # La firma se hace acá (y no adentro de `_pay_x402`) porque tiene
            # que cubrir el JSON canónico de `contents` YA armado -- el
            # mandato completo, no solo el payload de pago.
            signer = self._credential
            assert isinstance(signer, WalletSigner)
            signature = signer.sign_message(contents_bytes)
            user_authorization = base64.urlsafe_b64encode(signature).decode()

        mandate = PaymentMandate(payment_mandate_contents=contents, user_authorization=user_authorization)
        return base64.urlsafe_b64encode(_canonical_json(mandate.model_dump(mode="json"))).decode()

    def _pay_x402(self, pay_data: dict[str, Any]) -> tuple[dict[str, Any], str]:
        requirements = PaymentRequirements(
            scheme="exact",
            network=pay_data["network"],
            asset=pay_data["asset"],
            amount=pay_data["amount"],
            pay_to=pay_data["payTo"],
            max_timeout_seconds=pay_data.get("maxTimeoutSeconds", _CART_TTL_SECONDS),
            extra={"name": pay_data["assetName"], "version": pay_data["assetVersion"]},
        )
        assert self._scheme is not None
        inner_payload = self._scheme.create_payment_payload(requirements)
        payment_payload = PaymentPayload(payload=inner_payload, accepted=requirements)
        # `user_authorization` real se calcula después de armar `contents`
        # completo -- ver `_build_payment_mandate_header`.
        return {"x402Payload": payment_payload.model_dump(mode="json")}, ""

    def _pay_aibank(self, pay_data: dict[str, Any]) -> tuple[dict[str, Any], str]:
        credential = self._credential
        assert isinstance(credential, AIBankCredential)
        assert self._bank is not None

        amount = Decimal(parse_money(pay_data["price"])["amount"])
        authorization = self._bank.authorize(
            credential=credential,
            pay_to_account_id=pay_data["payTo"],
            amount=amount,
            idempotency_key=uuid.uuid4().hex,
        )
        self._bank.capture(authorization_id=authorization.id, credential=credential)

        details = {
            "aibankPayload": {"authorization_id": authorization.id, "payer_account_id": credential.account_id}
        }
        # AIBank no tiene firma (ver docstring del módulo) -- se deja un
        # marcador no vacío para no romper el esquema pydantic de
        # `PaymentMandate.user_authorization` (campo string obligatorio); la
        # garantía real la da la verificación contra el banco en `redeem`.
        marker = base64.urlsafe_b64encode(
            json.dumps({"aibank_account_id": credential.account_id}).encode()
        ).decode()
        return details, marker

    async def aclose(self) -> None:
        await self._http.aclose()


def _receipt_from_headers(headers: Any) -> PaymentReceipt | None:
    header_value = headers.get(_AP2_SETTLEMENT_HEADER)
    if not header_value:
        return None
    raw = json.loads(base64.urlsafe_b64decode(header_value))
    settle = raw["settle"]
    amount_usd = Decimal(settle["amount"]) if settle.get("amount") else Decimal(0)
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
        # Riel por defecto cuando nadie pide uno específico (CLI/ejemplos:
        # `Settings.ap2_settlement`, fijo por proceso -- ahí sí tiene sentido
        # reiniciar para cambiarlo, como cualquier otra `Settings`). El
        # dashboard en cambio pasa su propio `rail_resolver` a `mount_seller`
        # para resolverlo en caliente por request (RM-18/RM-19) -- por eso
        # el facilitator de x402 Y el `MockAIBank` se construyen los DOS acá,
        # sin importar `ap2_settlement`: cualquiera de los dos rieles puede
        # pedirse en cualquier momento.
        self._default_rail = self._settings.ap2_settlement
        # Clave de identidad del comerciante para firmar CartMandate -- distinta,
        # a propósito, de `pay_to` (la dirección que RECIBE los fondos) y
        # del riel de liquidación: en el mundo real la identidad de firma y
        # la wallet/cuenta de cobro no tienen por qué ser la misma, y afirmar
        # "soy este comerciante" no depende de cómo se cobra.
        self._merchant_signer = LocalEoaSigner()

        from agent_commerce.payments.mock_aibank import MockAIBank

        self._bank: MockAIBank = MockAIBank()
        self._facilitator = build_facilitator_client(self._settings)

    def mount_seller(
        self,
        app: FastAPI,
        *,
        pay_to: str,
        prices: dict[str, str],
        aibank_pay_to: str | None = None,
        rail_resolver: Callable[[], SettlementRail] | None = None,
    ) -> None:
        """`aibank_pay_to`/`rail_resolver` son opcionales, solo los usa el
        dashboard (RM-18/RM-19) para poder ofrecer cualquiera de los dos
        rieles en caliente -- sin ellos, el comportamiento es el de siempre
        (CLI/ejemplos/tests): un único riel fijo, `self._default_rail`."""
        from fastapi.responses import JSONResponse

        state = _AP2SellerState(
            network=self._settings.network,
            pay_to=pay_to,
            aibank_pay_to=aibank_pay_to if aibank_pay_to is not None else pay_to,
            prices=prices,
            merchant_signer=self._merchant_signer,
            merchant_name=self._merchant_name,
            rail_resolver=rail_resolver or (lambda: self._default_rail),
            facilitator=self._facilitator,
            bank=self._bank,
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
                settle, payment_mandate_id = await state.redeem(header_value)
            except AP2Error as exc:
                return JSONResponse(status_code=402, content={"error": str(exc)})

            response = await call_next(request)
            payload = {
                "settle": settle,
                "pay_to": settle.get("pay_to", pay_to),
                "payment_mandate_id": payment_mandate_id,
            }
            response.headers[_AP2_SETTLEMENT_HEADER] = base64.urlsafe_b64encode(
                _canonical_json(payload)
            ).decode()
            return response

    def build_buyer_client(self, signer: PayerCredential) -> BuyerClient:
        # El riel lo decide el TIPO de credencial que trajo el comprador, no
        # un estado fijo del protocolo (RM-18/RM-19): así el dashboard puede
        # cambiar de backend de wallet en caliente y el próximo pago sigue
        # el riel correcto sin reiniciar el proceso. `self._bank`/
        # `self._facilitator` siempre están construidos (ver `__init__`).
        if isinstance(signer, AIBankCredential):
            return _AP2BuyerClient(httpx.AsyncClient(), signer, SettlementRail.AIBANK, _bank=self._bank)
        assert isinstance(signer, WalletSigner)
        scheme = ExactEvmClientScheme(signer)
        return _AP2BuyerClient(httpx.AsyncClient(), signer, SettlementRail.X402, _scheme=scheme)
