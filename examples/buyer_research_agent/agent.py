"""Comprador de ejemplo: un agente de "investigación" que paga servicios del catálogo.

Envuelve `PayingAgent` (framework) con un método de negocio de más alto
nivel (`summarize`) -- así es como se ve, desde afuera, un agente que
"aprovecha el modelo de negocio": no maneja protocolos de pago él mismo,
solo pide capacidades por nombre.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from agent_commerce.client.paying_agent import PayingAgent, ServiceCallResult

if TYPE_CHECKING:
    from agent_commerce.catalog.registry import ServiceRegistry
    from agent_commerce.payments.protocols.base import PayerCredential, PaymentProtocol


class ResearchAgent:
    def __init__(
        self,
        *,
        protocol: PaymentProtocol,
        signer: PayerCredential,
        catalog: ServiceRegistry,
    ) -> None:
        self._paying_agent = PayingAgent(protocol=protocol, signer=signer, catalog=catalog)

    async def summarize(self, text: str, max_sentences: int = 2) -> ServiceCallResult:
        return await self._paying_agent.call_service(
            "summarize", {"text": text, "max_sentences": max_sentences}
        )

    async def aclose(self) -> None:
        await self._paying_agent.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
