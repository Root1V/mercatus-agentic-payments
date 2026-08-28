"""Puerto de protocolo de pago: cómo se negocia/autoriza/liquida un pago.

Cualquier adaptador (`X402Protocol`, `AP2Protocol`, futuros) implementa esta
interfaz. `server/monetize.py` y `client/paying_agent.py` programan
únicamente contra ella: no saben ni les importa qué protocolo de pago hay
detrás, así que el mismo código de negocio (vendedor y comprador) corre
igual sobre x402 o sobre AP2.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agent_commerce.payments.wallets.base import WalletSigner


@dataclass
class PaymentReceipt:
    """Comprobante de un pago completado, protocolo-agnóstico."""

    protocol: str
    network: str
    payer: str
    pay_to: str
    amount_usd: Decimal
    settlement_id: str  # tx_hash (x402) o payment_mandate_id (AP2)
    raw: dict[str, Any]


@dataclass
class PaidResponse:
    status_code: int
    json_body: Any
    receipt: PaymentReceipt | None


class BuyerClient(abc.ABC):
    """Cliente HTTP que paga automáticamente los recursos protegidos que llama."""

    @abc.abstractmethod
    async def request(
        self, method: str, url: str, *, json: dict[str, Any] | None = None
    ) -> PaidResponse: ...

    @abc.abstractmethod
    async def aclose(self) -> None: ...


class PaymentProtocol(abc.ABC):
    """Adaptador de protocolo de pago (x402, AP2, ...)."""

    name: str

    @abc.abstractmethod
    def mount_seller(
        self,
        app: FastAPI,
        *,
        pay_to: str,
        prices: dict[str, str],
    ) -> None:
        """Monta la protección de pago sobre `app` para las rutas de `prices`.

        `prices` mapea `"MÉTODO /ruta"` -> precio (`"$0.001"`).
        """

    @abc.abstractmethod
    def build_buyer_client(self, signer: WalletSigner) -> BuyerClient:
        """Construye un cliente HTTP que paga automáticamente con `signer`."""
