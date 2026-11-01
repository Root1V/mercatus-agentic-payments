"""Con qué cuenta de AIBank (hoy Aerarium) paga un rol, en los dos modelos
de `13-spec-modelos-a-y-b.md` (RM-18).

Ninguna de las dos lleva un secreto: en la API real quien se autentica es la
**integración** (Mercatus, un token OAuth2 `client_credentials`), que actúa
en nombre de sus agentes -- ver `aibank_api.py`. Un agente es solo una
`account_id`, y lo que lo limita son los topes de su cuenta (AE-02). Por eso
tampoco implementan `WalletSigner` (`payments/wallets/base.py`): no hay
custodio criptográfico ni firma; la prueba de pago es que el banco haya
autorizado y capturado. AIBank es un segundo riel de liquidación de
`AP2Protocol`, no un `PaymentProtocol` aparte.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AIBankSubAccount:
    """Modelo A (ómnibus): una sub-cuenta que la integración de Mercatus abrió
    para un agente (`POST /v1/accounts`, idempotente por `owner_reference`).
    El dinero que hay ahí lo custodia Mercatus."""

    account_id: str

    @property
    def address(self) -> str:
        """Alias esperado por el resto del framework (CLI, dashboard), que
        trata "address" como el identificador genérico de pagador/receptor
        -- sea una dirección EVM (rieles cripto) o, acá, una cuenta bancaria.
        """
        return self.account_id


@dataclass(frozen=True)
class AIBankMandateCredential:
    """Modelo B (cuenta propia): la cuenta es de un cliente del banco, y la
    autoridad para sacar dinero de ella la da un **mandato** que su titular
    aprobó en la app del banco (doc 13 §3.2) -- no algo que Mercatus posea.

    No hereda de `AIBankSubAccount` a propósito: no es "una cuenta nuestra",
    es "un permiso que otra persona concedió sobre la suya"."""

    mandate_id: str
    account_id: str

    @property
    def address(self) -> str:
        return self.account_id
