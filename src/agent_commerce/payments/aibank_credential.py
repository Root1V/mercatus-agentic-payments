"""Puertos de credencial AIBank: cómo se autentica el agente ante su banco
(RM-18), en los dos modelos que especifica `13-spec-modelos-a-y-b.md`.

A diferencia de `WalletSigner` (`payments/wallets/base.py`), acá no hay
custodio criptográfico ni firma: la prueba de pago es haber autenticado con
éxito contra el banco (autorizar + capturar una transferencia), no una firma
EIP-712/EIP-191. Por eso ninguna de estas credenciales implementa
`WalletSigner` -- forzarlas en ese molde sería una abstracción falsa (ver
`docs/roadmap.md` RM-18). AIBank es un segundo riel de liquidación de
`AP2Protocol` (`payments/protocols/ap2_protocol.py`), no un `PaymentProtocol`
aparte: AP2 ya está diseñado para ser agnóstico al riel real de pago.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass


class AIBankCredential:
    """Modelo A (ómnibus): cuenta + API key de un agente bajo el paraguas
    de Mercatus en AIBank (o cualquier banco que implemente el mismo
    contrato REST -- ver `docs/roadmap.md` RM-18).

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


@dataclass
class AIBankMandateCredential:
    """Modelo B (cuenta propia): la autoridad para pagar no la da una API
    key que el agente posea -- la da un **mandato** que un titular real de
    AIBank ya aprobó fuera de este framework, en la app del banco
    (`13-spec-modelos-a-y-b.md` §3.2). Por eso esta credencial NO tiene
    secreto propio, solo referencia un permiso ya otorgado: `mandate_id`
    (de `MockAIBank.request_consent` + aprobación) y la `account_id` del
    titular que lo concedió.

    No hereda de `AIBankCredential` a propósito -- conceptualmente no es
    "una cuenta con su clave", es "un permiso ya concedido por otra
    persona"; mezclarlas en una sola clase escondería esa diferencia real
    detrás de campos opcionales sin sentido en un lado o el otro.
    """

    mandate_id: str
    account_id: str

    @property
    def address(self) -> str:
        return self.account_id
