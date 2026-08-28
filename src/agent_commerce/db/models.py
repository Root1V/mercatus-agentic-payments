"""Modelos ORM (SQLAlchemy 2.0, estilo `Mapped[...]`).

Tres tablas: `users` (auth), `catalog_listings` (catálogo editable desde el
dashboard) y `ledger_entries` (historial de llamadas de prueba). Nada de
esto lo usa el framework "core" (`payments/`, `catalog/registry.py`,
`client/`, `server/`) -- solo `agent_commerce.dashboard` y
`agent_commerce.auth` dependen de este paquete.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Numeric, String, Text, func
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
