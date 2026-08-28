"""Stub best-effort de un catálogo respaldado por el marketplace real de
agents.circle.com.

No se confirmó, investigando desde este framework, una API de discovery
pública y documentada del marketplace de Circle (a agosto de 2026 su
interfaz principal es la web en agents.circle.com, no un endpoint REST
publicado). En vez de adivinar una URL/contrato, este adaptador falla
explícitamente hasta que se confirme el endpoint real -- así nunca finge
silenciosamente que hay datos reales cuando no los hay.
"""

from __future__ import annotations

from .models import ServiceListing
from .registry import ServiceRegistry


class CircleMarketplaceRegistry(ServiceRegistry):
    def __init__(self, *, api_base_url: str, api_key: str | None = None) -> None:
        self._api_base_url = api_base_url
        self._api_key = api_key

    async def search(self, query: str) -> list[ServiceListing]:
        raise NotImplementedError(
            "No hay una API de discovery pública confirmada para el marketplace de "
            "agents.circle.com. Usa InMemoryServiceRegistry (catálogo simulado) o "
            "implementa aquí el endpoint real una vez confirmado su contrato."
        )

    async def get(self, service_id: str) -> ServiceListing:
        raise NotImplementedError(
            "No hay una API de discovery pública confirmada para el marketplace de "
            "agents.circle.com. Usa InMemoryServiceRegistry (catálogo simulado) o "
            "implementa aquí el endpoint real una vez confirmado su contrato."
        )
