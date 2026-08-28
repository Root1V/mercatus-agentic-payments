"""Puertos de persistencia del dashboard: `LedgerStore` y `CatalogStore`.

Mismo estilo que `payments/wallets/base.py`/`payments/protocols/base.py`:
`dashboard/app.py` programa solo contra estos `Protocol`, nunca contra
SQLAlchemy directamente -- así el dashboard puede correr con Postgres real
(`adapters/sql_*_store.py`) o con un store en memoria (`adapters/memory_*_store.py`,
usado en tests) sin cambiar una línea de la app.

`CatalogStore` es un puerto DISTINTO de `catalog/registry.py::ServiceRegistry`:
`ServiceRegistry` es para que `PayingAgent` *descubra* servicios
(`search`/`get`, de solo lectura); `CatalogStore` es para que el dashboard
*administre* el catálogo (crear/listar/borrar). Mezclar ambas
responsabilidades en un solo puerto violaría separación de intereses -- un
comprador no necesita poder borrar un listing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from agent_commerce.catalog.models import ServiceListing


@dataclass
class LedgerEntry:
    id: int
    timestamp: datetime
    protocol: str
    capability: str
    service_id: str
    payer: str
    pay_to: str
    amount_usd: Decimal
    settlement_id: str
    status: str  # "ok" | "error"
    detail: str | None = None


@runtime_checkable
class LedgerStore(Protocol):
    def record(
        self,
        *,
        protocol: str,
        capability: str,
        service_id: str,
        payer: str,
        pay_to: str,
        amount_usd: Decimal,
        settlement_id: str,
        status: str,
        detail: str | None = None,
    ) -> LedgerEntry: ...

    def recent(self, limit: int = 50) -> list[LedgerEntry]: ...

    def stats(self) -> dict: ...


@runtime_checkable
class CatalogStore(Protocol):
    def list_all(self) -> list[ServiceListing]: ...

    def get(self, listing_id: str) -> ServiceListing | None: ...

    def create(self, listing: ServiceListing, *, is_seed: bool = False) -> ServiceListing: ...

    def update(self, listing_id: str, listing: ServiceListing) -> ServiceListing | None:
        """Reemplaza los campos editables de un listing existente. `None` si no existe."""
        ...

    def delete(self, listing_id: str) -> bool: ...

    def seed_from_json_if_empty(self, path: str) -> int:
        """Siembra el catálogo desde un JSON si está vacío. Devuelve cuántos insertó."""
        ...
