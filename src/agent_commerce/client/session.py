"""Construcción del transporte HTTP con pago automático, agnóstica de protocolo.

Existe como módulo separado (en vez de inlinearlo en `paying_agent.py`) para
que quede un único punto donde `PaymentProtocol.build_buyer_client(signer)`
se invoca del lado comprador -- útil si en el futuro hace falta cachear o
reutilizar sesiones entre llamadas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_commerce.payments.protocols.base import BuyerClient, PaymentProtocol
    from agent_commerce.payments.wallets.base import WalletSigner


def build_buyer_client(protocol: PaymentProtocol, signer: WalletSigner) -> BuyerClient:
    return protocol.build_buyer_client(signer)
