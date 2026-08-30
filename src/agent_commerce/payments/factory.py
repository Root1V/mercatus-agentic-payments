"""Composición: `Settings` -> (`PaymentProtocol`, fábrica de `WalletSigner`).

Único lugar del framework que sabe que "x402"/"ap2" y "local"/"circle" son
nombres concretos. Todo lo demás (server, client, examples) recibe objetos
ya construidos contra los puertos `PaymentProtocol`/`WalletSigner`.

AIBank (RM-18) no es un protocolo aparte: es un segundo riel de liquidación
de AP2 (`Settings.ap2_settlement`), resuelto adentro de `AP2Protocol` --
ver `protocols/ap2_protocol.py` y `docs/roadmap.md` RM-18. Por eso
`build_payer_credential` (no `build_wallet_signer`) es el punto de entrada
correcto para cualquier código nuevo que no sepa de antemano si el
comprador va a necesitar un `WalletSigner` o una `AIBankCredential`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import Protocol, Settings, SettlementRail, WalletBackend, get_settings
from .protocols.base import PaymentProtocol
from .wallets.base import WalletSigner

if TYPE_CHECKING:
    from .aibank_credential import AIBankCredential


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


def build_payer_credential(
    *, role: str, settings: Settings | None = None, private_key: str | None = None
) -> WalletSigner | AIBankCredential:
    """Punto de composición único para "con qué paga este rol" (RM-18): si
    el protocolo activo es AP2 con `ap2_settlement=aibank`, arma una
    `AIBankCredential` desde `Settings`; para cualquier otra combinación
    delega en `build_wallet_signer` sin cambios. Preferí esto a
    `build_wallet_signer` en código nuevo que no sepa de antemano qué
    riel de liquidación está activo."""
    settings = settings or get_settings()

    if settings.protocol is Protocol.AP2 and settings.ap2_settlement is SettlementRail.AIBANK:
        from .aibank_credential import AIBankCredential

        account_id = (
            settings.aibank_buyer_account_id if role == "buyer" else settings.aibank_seller_account_id
        )
        api_key = settings.aibank_buyer_api_key if role == "buyer" else settings.aibank_seller_api_key
        return AIBankCredential(
            account_id=account_id, api_key=api_key.get_secret_value() if api_key else None
        )

    return build_wallet_signer(role=role, settings=settings, private_key=private_key)
