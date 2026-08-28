"""Puertos de persistencia del dashboard: `LedgerStore`, `CatalogStore` y `AgentStore`.

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
from typing import Any, Protocol, runtime_checkable

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


@dataclass
class Agent:
    id: int
    owner_user_id: int
    name: str
    instructions: str
    llm_model: str
    protocol: str  # "x402" | "ap2"
    spend_limit_usd: Decimal | None
    created_at: datetime


@dataclass
class AgentConversation:
    id: int
    agent_id: int
    title: str
    created_at: datetime


@dataclass
class AgentMessage:
    id: int
    conversation_id: int
    role: str  # "user" | "agent"
    content: str
    trace: list[dict[str, Any]] | None
    total_spent_usd: Decimal | None
    created_at: datetime


@runtime_checkable
class AgentStore(Protocol):
    """Persistencia del playground de agentes (RM-13): agentes, sus
    conversaciones y los mensajes de cada una. Deliberadamente un solo
    puerto para las tres entidades -- siempre se usan juntas (no tiene
    sentido un `AgentConversation` sin su `Agent`), a diferencia de
    `CatalogStore`/`LedgerStore` que sí son independientes entre sí.
    """

    def create_agent(
        self,
        *,
        owner_user_id: int,
        name: str,
        instructions: str,
        llm_model: str,
        protocol: str,
        spend_limit_usd: Decimal | None,
    ) -> Agent: ...

    def list_agents(self, *, owner_user_id: int) -> list[Agent]: ...

    def get_agent(self, agent_id: int) -> Agent | None: ...

    def delete_agent(self, agent_id: int) -> bool: ...

    def create_conversation(self, *, agent_id: int, title: str) -> AgentConversation: ...

    def list_conversations(self, agent_id: int) -> list[AgentConversation]: ...

    def get_conversation(self, conversation_id: int) -> AgentConversation | None: ...

    def add_message(
        self,
        *,
        conversation_id: int,
        role: str,
        content: str,
        trace: list[dict[str, Any]] | None = None,
        total_spent_usd: Decimal | None = None,
    ) -> AgentMessage: ...

    def list_messages(self, conversation_id: int) -> list[AgentMessage]: ...
