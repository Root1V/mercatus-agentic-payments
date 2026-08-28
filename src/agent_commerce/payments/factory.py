"""Composición: `Settings` -> (`PaymentProtocol`, fábrica de `WalletSigner`).

Único lugar del framework que sabe que "x402"/"ap2" y "local"/"circle" son
nombres concretos. Todo lo demás (server, client, examples) recibe objetos
ya construidos contra los puertos `PaymentProtocol`/`WalletSigner`.
"""

from __future__ import annotations

from ..config import Protocol, Settings, WalletBackend, get_settings
from .protocols.base import PaymentProtocol
from .wallets.base import WalletSigner


def get_payment_protocol(settings: Settings | None = None) -> PaymentProtocol:
    settings = settings or get_settings()
    if settings.protocol is Protocol.X402:
        from .protocols.x402_protocol import X402Protocol

        return X402Protocol(settings)
    if settings.protocol is Protocol.AP2:
        from .protocols.ap2_protocol import AP2Protocol

        return AP2Protocol(settings)
    raise ValueError(f"Protocolo no soportado: {settings.protocol}")  # pragma: no cover


def build_wallet_signer(
    *, role: str, settings: Settings | None = None, private_key: str | None = None
) -> WalletSigner:
    """`role` es `"buyer"` o `"seller"`: decide qué credenciales de `.env` usar
    cuando el backend es `circle` (cada rol tiene su propio wallet_id)."""
    settings = settings or get_settings()

    if settings.wallet_backend is WalletBackend.LOCAL:
        from .wallets.local_eoa import LocalEoaSigner

        key = private_key
        if key is None:
            secret = settings.buyer_private_key if role == "buyer" else settings.seller_private_key
            key = secret.get_secret_value() if secret else None
        return LocalEoaSigner(private_key=key)

    if settings.wallet_backend is WalletBackend.CIRCLE:
        from .wallets.circle_wallet import CircleWalletSigner

        wallet_id = settings.circle_buyer_wallet_id if role == "buyer" else settings.circle_seller_wallet_id
        if not (wallet_id and settings.circle_api_key and settings.circle_entity_secret):
            raise ValueError(
                "wallet_backend=circle requiere AGENT_COMMERCE_CIRCLE_API_KEY, "
                "AGENT_COMMERCE_CIRCLE_ENTITY_SECRET y "
                f"AGENT_COMMERCE_CIRCLE_{role.upper()}_WALLET_ID en .env"
            )
        return CircleWalletSigner(
            wallet_id=wallet_id,
            api_key=settings.circle_api_key.get_secret_value(),
            entity_secret=settings.circle_entity_secret.get_secret_value(),
        )

    raise ValueError(f"Backend de wallet no soportado: {settings.wallet_backend}")  # pragma: no cover
