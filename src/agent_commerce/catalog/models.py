"""Modelo de un servicio listado en el catálogo (simula un marketplace tipo
agents.circle.com: agentes descubren y pagan servicios de terceros)."""

from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field


class ServiceListing(BaseModel):
    id: str
    name: str
    description: str
    method: Literal["GET", "POST"]
    url: AnyHttpUrl
    price_usd: str
    capability_tags: list[str] = Field(default_factory=list)
    protocols: list[str] = Field(default_factory=lambda: ["x402"])
    provider_name: str = "agent_commerce demo"
