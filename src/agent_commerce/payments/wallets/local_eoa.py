"""Wallet de referencia: clave local (eth_account), sin custodio externo.

Backend DEFAULT del framework. No requiere cuenta ni credenciales de ningún
proveedor -- por eso `pip install agent-commerce` (sin extras) alcanza para
correr todo el framework en modo mock, y también en modo testnet si se le
da una clave financiada manualmente en vez de usar el adaptador de Circle.
"""

from __future__ import annotations

from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_account.signers.local import LocalAccount
from x402.mechanisms.evm.signers import EthAccountSigner


class LocalEoaSigner:
    """Firma con una cuenta EVM (`eth_account`) mantenida en memoria del proceso.

    En modo mock la cuenta es efímera (se genera al vuelo, nunca toca una
    red real). En modo testnet se puede fijar `private_key` para reutilizar
    la misma dirección entre corridas (por ejemplo una ya financiada con
    USDC de Base Sepolia).
    """

    def __init__(self, private_key: str | None = None) -> None:
        self._account: LocalAccount = (
            Account.from_key(private_key) if private_key else Account.create()
        )
        # Reutiliza la implementación de firma EIP-712 real de x402 en vez de
        # reimplementarla: es la parte criptográfica, no la de custodia.
        self._x402_signer = EthAccountSigner(self._account)

    @property
    def address(self) -> str:
        return self._account.address

    def sign_typed_data(
        self,
        domain: Any,
        types: dict[str, list[Any]],
        primary_type: str,
        message: dict[str, Any],
    ) -> bytes:
        return self._x402_signer.sign_typed_data(domain, types, primary_type, message)

    def sign_message(self, message: bytes) -> bytes:
        signed = self._account.sign_message(encode_defunct(primitive=message))
        return bytes(signed.signature)
