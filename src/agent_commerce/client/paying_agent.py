"""Lado comprador: un agente que descubre servicios en el catálogo y los paga.

Agnóstico de protocolo de pago -- solo conoce el puerto `BuyerClient`
(`payments/protocols/base.py`), construido por `session.build_buyer_client`
a partir del `PaymentProtocol` activo (x402 o AP2, según configuración).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Self

from .session import build_buyer_client

if TYPE_CHECKING:
    from agent_commerce.catalog.models import ServiceListing
    from agent_commerce.catalog.registry import ServiceRegistry
    from agent_commerce.payments.protocols.base import (
        PayerCredential,
        PaymentProtocol,
        PaymentReceipt,
    )


class NoMatchingServiceError(LookupError):
    pass


@dataclass
class ServiceCallResult:
    data: Any
    price_paid_usd: Decimal | None
    receipt: PaymentReceipt | None
    listing: ServiceListing


class PayingAgent:
    """Agente que descubre servicios en `catalog` y los llama pagando con `signer`
    sobre el `protocol` de pago activo."""

    def __init__(
        self,
        *,
        protocol: PaymentProtocol,
        signer: PayerCredential,
        catalog: ServiceRegistry,
    ) -> None:
        self._protocol = protocol
        self._signer = signer
        self._catalog = catalog
        self._client = build_buyer_client(protocol, signer)

    async def discover(self, query: str) -> list[ServiceListing]:
        return await self._catalog.search(query)

    async def call_service(
        self, capability: str, payload: dict[str, Any] | None = None
    ) -> ServiceCallResult:
        matches = await self._catalog.search(capability)
        if not matches:
            raise NoMatchingServiceError(
                f"Ningún servicio del catálogo coincide con '{capability}'"
            )
        listing = matches[0]

        response = await self._client.request(listing.method, str(listing.url), json=payload)
        if response.status_code >= 400:
            raise RuntimeError(
                f"El servicio '{listing.id}' respondió {response.status_code}: {response.json_body}"
            )

        price_paid = response.receipt.amount_usd if response.receipt else None
        return ServiceCallResult(
            data=response.json_body,
            price_paid_usd=price_paid,
            receipt=response.receipt,
            listing=listing,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
