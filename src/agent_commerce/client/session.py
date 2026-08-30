"""Construcción del transporte HTTP con pago automático, agnóstica de protocolo.

Existe como módulo separado (en vez de inlinearlo en `paying_agent.py`) para
que quede un único punto donde `PaymentProtocol.build_buyer_client(signer)`
se invoca del lado comprador -- útil si en el futuro hace falta cachear o
reutilizar sesiones entre llamadas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_commerce.payments.protocols.base import BuyerClient, PayerCredential, PaymentProtocol


def build_buyer_client(protocol: PaymentProtocol, signer: PayerCredential) -> BuyerClient:
    # `protocol` está tipado por el ABC base (`WalletSigner` únicamente) --
    # solo `AP2Protocol.build_buyer_client` de verdad acepta el `PayerCredential`
    # completo (`WalletSigner | AIBankCredential`, ver `protocols/base.py`).
    # La correspondencia correcta protocolo<->credencial la garantizan las
    # factories (`payments/factory.py`), no algo que mypy pueda probar acá
    # sin generics -- mismo criterio que otros `type: ignore` puntuales ya
    # existentes en el proyecto.
    return protocol.build_buyer_client(signer)  # type: ignore[arg-type]
