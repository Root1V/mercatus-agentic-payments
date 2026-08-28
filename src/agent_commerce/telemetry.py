"""Logging estructurado de eventos de pago, agnóstico de protocolo."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_commerce.payments.protocols.base import PaymentReceipt

logger = logging.getLogger("agent_commerce.payments")


def log_payment(event: str, *, receipt: PaymentReceipt | None, **extra: object) -> None:
    if receipt is None:
        logger.info("%s protocol=? payer=? amount=? settlement=?", event, extra=extra)
        return
    logger.info(
        "%s protocol=%s network=%s payer=%s amount_usd=%s settlement_id=%s",
        event,
        receipt.protocol,
        receipt.network,
        receipt.payer,
        receipt.amount_usd,
        receipt.settlement_id,
        extra=extra,
    )
