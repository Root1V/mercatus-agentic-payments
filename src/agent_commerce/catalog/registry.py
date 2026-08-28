"""Catálogo de servicios pagos: puerto + implementación en memoria.

`InMemoryServiceRegistry` simula el marketplace de agents.circle.com (900+
servicios pagos por llamada) para poder desarrollar y probar sin red ni
credenciales. Un catálogo real (ver `circle_marketplace.py`, stub) solo
necesitaría implementar el mismo puerto `ServiceRegistry`.
"""

from __future__ import annotations

import abc
import json
from pathlib import Path

from .models import ServiceListing


class ServiceRegistry(abc.ABC):
    @abc.abstractmethod
    async def search(self, query: str) -> list[ServiceListing]: ...

    @abc.abstractmethod
    async def get(self, service_id: str) -> ServiceListing: ...


class ServiceNotFoundError(KeyError):
    pass


class InMemoryServiceRegistry(ServiceRegistry):
    def __init__(self, listings: list[ServiceListing]) -> None:
        self._by_id = {listing.id: listing for listing in listings}

    @classmethod
    def from_json_file(cls, path: str | Path) -> InMemoryServiceRegistry:
        data = json.loads(Path(path).read_text())
        return cls([ServiceListing.model_validate(entry) for entry in data])

    def all(self) -> list[ServiceListing]:
        return list(self._by_id.values())

    async def search(self, query: str) -> list[ServiceListing]:
        query_lower = query.lower()
        return [
            listing
            for listing in self._by_id.values()
            if query_lower in listing.name.lower()
            or query_lower in listing.description.lower()
            or any(query_lower in tag.lower() for tag in listing.capability_tags)
        ]

    async def get(self, service_id: str) -> ServiceListing:
        try:
            return self._by_id[service_id]
        except KeyError as exc:
            raise ServiceNotFoundError(service_id) from exc
