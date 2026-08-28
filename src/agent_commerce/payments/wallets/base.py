"""Puerto de custodia de wallet: quién firma las autorizaciones de pago.

Deliberadamente no importa nada de x402, AP2 ni de ningún proveedor
concreto: cualquier implementación que exponga esta forma sirve tanto para
el adaptador x402 (que espera exactamente esta interfaz vía su propio
protocolo `ClientEvmSigner`) como para el adaptador AP2 (que reutiliza
`sign_message` para firmar mandatos). Este es el punto de intercambio
mock/testnet y local/Circle: nada por encima de este puerto sabe qué lo
implementa.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WalletSigner(Protocol):
    """Firmante EVM genérico. La forma coincide a propósito con
    `x402.mechanisms.evm.signer.ClientEvmSigner` para que cualquier
    implementación pueda pasarse directo a `register_exact_evm_client` sin
    una capa de adaptación adicional.
    """

    @property
    def address(self) -> str: ...

    def sign_typed_data(
        self,
        domain: Any,
        types: dict[str, list[Any]],
        primary_type: str,
        message: dict[str, Any],
    ) -> bytes:
        """Firma EIP-712 typed data (usado por el adaptador x402)."""
        ...

    def sign_message(self, message: bytes) -> bytes:
        """Firma EIP-191 (personal_sign) de un mensaje arbitrario.

        Usado por el adaptador AP2 para firmar el JSON canónico de un
        mandato, donde no aplica un esquema EIP-712 tipado como en x402.
        """
        ...
