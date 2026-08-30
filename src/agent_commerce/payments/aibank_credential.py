"""Puerto de credencial AIBank: cómo se autentica el agente ante su banco (RM-18).

A diferencia de `WalletSigner` (`payments/wallets/base.py`), acá no hay
custodio criptográfico ni firma: la prueba de pago es haber autenticado con
éxito contra el banco (autorizar + capturar una transferencia) con la API
key de la cuenta, no una firma EIP-712/EIP-191. Por eso esta credencial NO
implementa `WalletSigner` -- forzarla en ese molde sería una abstracción
falsa (ver `docs/roadmap.md` RM-18). AIBank es un segundo riel de
liquidación de `AP2Protocol` (`Settings.ap2_settlement`,
`payments/protocols/ap2_protocol.py`), no un `PaymentProtocol` aparte: AP2
ya está diseñado para ser agnóstico al riel real de pago.
"""

from __future__ import annotations

import secrets
import uuid


class AIBankCredential:
    """Cuenta + API key de un agente en AIBank (o cualquier banco que
    implemente el mismo contrato REST -- ver `docs/roadmap.md` RM-18).

    En modo mock, si no se pasan `account_id`/`api_key`, se generan
    efímeros al vuelo -- mismo criterio que `LocalEoaSigner` sin
    `private_key`: no hace falta "abrir cuenta" en ningún lado antes de
    poder pagar. `MockAIBank` "abre" la cuenta la primera vez que la ve
    (ver `payments/mock_aibank.py`).
    """

    def __init__(self, account_id: str | None = None, api_key: str | None = None) -> None:
        self.account_id = account_id or f"aibank_{uuid.uuid4().hex[:16]}"
        self.api_key = api_key or f"sk_aibank_{secrets.token_hex(24)}"

    @property
    def address(self) -> str:
        """Alias esperado por el resto del framework (CLI, dashboard), que
        trata "address" como el identificador genérico de pagador/receptor
        -- sea una dirección EVM (rieles cripto) o, acá, una cuenta bancaria.
        """
        return self.account_id
