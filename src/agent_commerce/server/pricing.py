"""Helpers de precio, agnósticos de protocolo de pago."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PriceSpec:
    """Precio de una ruta monetizada, en dólares."""

    route: str  # "MÉTODO /ruta", p. ej. "POST /summarize"
    amount_usd: Decimal

    def as_price_string(self) -> str:
        return f"${self.amount_usd.normalize():f}" if self.amount_usd else "$0"


def prices_to_dict(specs: list[PriceSpec]) -> dict[str, str]:
    return {spec.route: spec.as_price_string() for spec in specs}
