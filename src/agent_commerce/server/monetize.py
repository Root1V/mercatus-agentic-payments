"""Único punto de entrada del lado vendedor: monetiza una app FastAPI.

No sabe ni le importa qué protocolo de pago hay detrás (x402, AP2, ...): eso
lo decide `protocol`, un `PaymentProtocol` ya construido (ver
`payments.factory.get_payment_protocol`). Este módulo es, a propósito, el
único lugar donde el código de negocio del vendedor (`examples/seller_text_summarizer`)
toca la capa de pagos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agent_commerce.payments.protocols.base import PaymentProtocol


def mount_payments(
    app: FastAPI,
    *,
    protocol: PaymentProtocol,
    pay_to: str,
    prices: dict[str, str],
) -> None:
    """Monetiza `app`: las rutas listadas en `prices` exigen pago antes de responder.

    `prices` mapea `"MÉTODO /ruta"` -> precio en dólares (p. ej. `{"POST /summarize": "$0.001"}`).
    """
    protocol.mount_seller(app, pay_to=pay_to, prices=prices)
