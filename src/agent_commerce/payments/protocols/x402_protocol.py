"""Adaptador de protocolo: x402 (Coinbase), el riel de liquidación cripto directo.

Servidor responde 402 con `accepts: PaymentRequirements[]`; el cliente
reintenta con el header `X-PAYMENT`/`PAYMENT-SIGNATURE` firmado; el servidor
confirma con el header `PAYMENT-RESPONSE`. Este módulo no reimplementa nada
de eso: envuelve `x402Client`/`x402ResourceServer` del SDK real de Coinbase
y solo decide (a) qué signer respalda al comprador -- vía el puerto
`WalletSigner`, nunca un proveedor concreto -- y (b) contra qué facilitator
verificar/liquidar: el `MockFacilitator` en memoria (modo mock) o un
facilitator HTTP remoto real (modo testnet).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from x402 import x402Client, x402ResourceServer
from x402.http import RoutesConfig
from x402.http.clients.httpx import x402HttpxClient
from x402.http.constants import PAYMENT_RESPONSE_HEADER, X_PAYMENT_RESPONSE_HEADER
from x402.http.middleware.fastapi import payment_middleware
from x402.http.utils import decode_payment_response_header
from x402.mechanisms.evm.exact import register_exact_evm_client, register_exact_evm_server

from agent_commerce.config import Settings, get_settings
from agent_commerce.payments.facilitator_selection import build_facilitator_client

from .base import BuyerClient, PaidResponse, PaymentProtocol, PaymentReceipt

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agent_commerce.payments.wallets.base import WalletSigner

_USDC_ATOMIC_UNITS = Decimal(10**6)


@dataclass
class _X402BuyerClient(BuyerClient):
    _client: x402HttpxClient

    async def request(
        self, method: str, url: str, *, json: dict[str, Any] | None = None
    ) -> PaidResponse:
        response = await self._client.request(method, url, json=json)
        receipt = _extract_receipt(response.headers)
        body = response.json() if response.content else None
        return PaidResponse(status_code=response.status_code, json_body=body, receipt=receipt)

    async def aclose(self) -> None:
        await self._client.aclose()


def _extract_receipt(headers: Any) -> PaymentReceipt | None:
    header_value = headers.get(PAYMENT_RESPONSE_HEADER) or headers.get(X_PAYMENT_RESPONSE_HEADER)
    if not header_value:
        return None
    settle_response = decode_payment_response_header(header_value)
    if not settle_response.success:
        return None
    amount_usd = (
        Decimal(settle_response.amount) / _USDC_ATOMIC_UNITS
        if settle_response.amount is not None
        else Decimal(0)
    )
    return PaymentReceipt(
        protocol="x402",
        network=str(settle_response.network),
        payer=settle_response.payer or "",
        pay_to="",
        amount_usd=amount_usd,
        settlement_id=settle_response.transaction,
        raw=settle_response.model_dump(mode="json"),
    )


class X402Protocol(PaymentProtocol):
    name = "x402"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # Un único facilitator compartido por instancia de protocolo: así
        # vendedor y (eventualmente) otros vendedores del mismo proceso ven
        # el mismo libro de saldos/nonces simulado (modo mock) o hablan con
        # el mismo facilitator remoto (modo testnet).
        self._facilitator = build_facilitator_client(self._settings)

    def mount_seller(self, app: FastAPI, *, pay_to: str, prices: dict[str, str]) -> None:
        server = x402ResourceServer(self._facilitator)
        register_exact_evm_server(server, networks=self._settings.network)

        routes = {
            route: {
                "accepts": {
                    "scheme": "exact",
                    "payTo": pay_to,
                    "price": price,
                    "network": self._settings.network,
                }
            }
            for route, price in prices.items()
        }

        middleware = payment_middleware(cast(RoutesConfig, routes), server)

        @app.middleware("http")
        async def _x402_payment_middleware(request: Any, call_next: Any) -> Any:
            return await middleware(request, call_next)

    def build_buyer_client(self, signer: WalletSigner) -> BuyerClient:
        client = x402Client()
        register_exact_evm_client(client, signer, networks=self._settings.network)
        return _X402BuyerClient(x402HttpxClient(client))
