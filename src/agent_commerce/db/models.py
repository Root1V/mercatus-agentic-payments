"""Modelos ORM (SQLAlchemy 2.0, estilo `Mapped[...]`).

`users` (auth), `catalog_listings` (catálogo editable desde el dashboard),
`ledger_entries` (historial de llamadas de prueba) y `agents`/
`agent_conversations`/`agent_messages` (playground de agentes, RM-13). Nada
de esto lo usa el framework "core" (`payments/`, `catalog/registry.py`,
`client/`, `server/`, `agentloop/`) -- solo `agent_commerce.dashboard` y
`agent_commerce.auth` dependen de este paquete.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogListingModel(Base):
    __tablename__ = "catalog_listings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug, p.ej. "text-summarizer"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(8))  # "GET" | "POST"
    url: Mapped[str] = mapped_column(String(500))
    price_usd: Mapped[str] = mapped_column(String(32))  # conserva el formato "$0.001"
    capability_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    protocols: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider_name: Mapped[str] = mapped_column(String(200), default="agent_commerce demo")
    is_seed: Mapped[bool] = mapped_column(default=False)  # sembrado desde catalog.sample.json
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LedgerEntryModel(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    protocol: Mapped[str] = mapped_column(String(16), index=True)  # "x402" | "ap2"
    capability: Mapped[str] = mapped_column(String(100))
    # Deliberadamente sin FK a catalog_listings.id: es un registro de auditoría
    # histórico -- un listing puede borrarse después de que se le hicieron
    # llamadas, o el valor puede ser "?" cuando no hubo match en el catálogo.
    service_id: Mapped[str] = mapped_column(String(64), index=True)
    payer: Mapped[str] = mapped_column(String(100))
    pay_to: Mapped[str] = mapped_column(String(100))
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    settlement_id: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(8), index=True)  # "ok" | "error"
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentModel(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # Instrucciones que el usuario agrega por encima del contrato JSON fijo
    # de AgentLoop (ver agentloop/loop.py) -- nunca lo reemplazan.
    instructions: Mapped[str] = mapped_column(Text, default="")
    llm_model: Mapped[str] = mapped_column(String(200))
    protocol: Mapped[str] = mapped_column(String(16))  # "x402" | "ap2"
    spend_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentConversationModel(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentMessageModel(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "agent"
    content: Mapped[str] = mapped_column(Text)
    # Solo para role="agent": traza paso a paso del AgentLoop (lista de
    # TraceStep serializados). Es una copia de lectura para mostrar en el
    # panel de traza (RM-15) -- los pagos reales de cada paso quedan (como
    # siempre) en `ledger_entries`, esto no es una segunda contabilidad.
    trace: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    total_spent_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class LlmSettingsModel(Base):
    """Fila única (singleton, `id=1`) con la conexión a Prometheus configurada
    desde el dashboard en vez de variables de entorno -- así quien administra
    el dashboard no necesita acceso al `.env` del servidor para conectar un
    LLM, solo las credenciales que le dio quien administra Prometheus."""

    __tablename__ = "llm_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    auth_base_url: Mapped[str] = mapped_column(String(500))
    gateway_base_url: Mapped[str] = mapped_column(String(500))
    client_id: Mapped[str] = mapped_column(String(200))
    client_secret: Mapped[str] = mapped_column(String(500))
    # Modelos habilitados para usar en agentes (los "contratados") -- lista
    # vacía = sin restricción, se ofrecen todos los que devuelva el gateway.
    allowed_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WalletSettingsModel(Base):
    """Fila única (singleton, `id=1`) con el backend de wallet del
    COMPRADOR configurado desde el dashboard (RM-06/RM-19) -- mismo espíritu
    que `LlmSettingsModel`. Solo afecta al comprador (`/api/test-call` y el
    playground de agentes); el vendedor de ejemplo sigue con su wallet local
    fija, definida al levantar el proceso (ver `dashboard/app.py`)."""

    __tablename__ = "wallet_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    backend: Mapped[str] = mapped_column(String(16))  # "local" | "circle"
    circle_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    circle_entity_secret: Mapped[str | None] = mapped_column(String(500), nullable=True)
    circle_wallet_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
