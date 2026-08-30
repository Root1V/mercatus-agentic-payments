"""AIBank 100% en memoria, sin red ni fondos reales (RM-18).

Implementa el contrato mínimo que se documentó en `docs/roadmap.md` RM-18
para "banco propio": autorizar, capturar, consultar y reembolsar una
transferencia entre dos cuentas, autenticado con una API key por cuenta (no
hay firma criptográfica -- ver `aibank_credential.py`).

Auth de cuentas: *trust-on-first-use*, igual que `MockFacilitator` no exige
"fondear" una dirección antes de poder pagar (arranca con saldo simulado la
primera vez que la ve). Acá, la primera vez que se ve un `account_id` queda
"abierta" con el `api_key` que trajo esa primera llamada; llamadas
posteriores para esa misma cuenta tienen que traer el mismo `api_key` o se
rechazan -- así se prueba de verdad el chequeo de credencial sin necesitar
un paso de setup separado (`open_account`) que ningún otro backend de este
framework tiene tampoco (Circle/local funcionan igual: la credencial ya
trae todo lo que hace falta).

No existe un "AIBank real" contra el cual liquidar en modo testnet (a
diferencia de x402, que sí tiene un facilitator público) -- esto es
deliberado, ver RM-18: el día que exista un proveedor real que hable este
mismo contrato REST, se agrega un cliente HTTP equivalente a
`facilitator_selection.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .aibank_credential import AIBankCredential

# Saldo simulado con el que arranca cualquier cuenta la primera vez que se
# usa -- en dólares, sin paso de "fondeo" (mismo criterio que
# `MockFacilitator._MOCK_STARTING_BALANCE`).
_MOCK_STARTING_BALANCE = Decimal(1000000000)


class AIBankError(Exception):
    """Cualquier rechazo de AIBank (credencial inválida, fondos
    insuficientes, estado inconsistente, etc.) -- el motivo va en
    `str(exc)`, mapeado a texto legible por el protocolo que envuelve esto."""


@dataclass
class Authorization:
    id: str
    payer_account_id: str
    pay_to_account_id: str
    amount: Decimal
    status: str  # "authorized" | "captured" | "refunded"
    idempotency_key: str


class MockAIBank:
    """Banco en memoria: cuentas, saldos, autorizaciones -- ver docstring del módulo."""

    def __init__(self) -> None:
        self._accounts: dict[str, str] = {}  # account_id -> api_key registrado
        self._balances: dict[str, Decimal] = {}
        self._authorizations: dict[str, Authorization] = {}
        self._idempotency: dict[tuple[str, str], str] = {}  # (account_id, key) -> authorization_id
        self.ledger: list[Authorization] = []

    def _check_auth(self, credential: AIBankCredential) -> None:
        known_key = self._accounts.get(credential.account_id)
        if known_key is None:
            self._accounts[credential.account_id] = credential.api_key
            self._balances[credential.account_id] = _MOCK_STARTING_BALANCE
            return
        if known_key != credential.api_key:
            raise AIBankError("invalid_credential")

    def authorize(
        self,
        *,
        credential: AIBankCredential,
        pay_to_account_id: str,
        amount: Decimal,
        idempotency_key: str,
    ) -> Authorization:
        """Reserva `amount` de la cuenta de `credential` a favor de
        `pay_to_account_id`, sin moverlo todavía (dos fases, como una
        autorización de tarjeta real). Reintentar con la misma
        `idempotency_key` devuelve la autorización ya creada en vez de
        duplicarla."""
        self._check_auth(credential)

        dedupe_key = (credential.account_id, idempotency_key)
        existing_id = self._idempotency.get(dedupe_key)
        if existing_id is not None:
            return self._authorizations[existing_id]

        if self._balances[credential.account_id] < amount:
            raise AIBankError("insufficient_funds")

        authorization = Authorization(
            id=f"auth_{uuid.uuid4().hex}",
            payer_account_id=credential.account_id,
            pay_to_account_id=pay_to_account_id,
            amount=amount,
            status="authorized",
            idempotency_key=idempotency_key,
        )
        self._authorizations[authorization.id] = authorization
        self._idempotency[dedupe_key] = authorization.id
        return authorization

    def capture(self, *, authorization_id: str, credential: AIBankCredential) -> Authorization:
        """Efectiviza una autorización previa: mueve el saldo de verdad.
        Solo la cuenta pagadora (dueña de la autorización) puede capturarla."""
        self._check_auth(credential)
        authorization = self._authorizations.get(authorization_id)
        if authorization is None:
            raise AIBankError("authorization_not_found")
        if authorization.payer_account_id != credential.account_id:
            raise AIBankError("authorization_belongs_to_another_account")
        if authorization.status != "authorized":
            raise AIBankError(f"cannot_capture_from_status_{authorization.status}")

        self._balances[authorization.payer_account_id] -= authorization.amount
        self._balances[authorization.pay_to_account_id] = (
            self._balances.get(authorization.pay_to_account_id, Decimal(0)) + authorization.amount
        )
        authorization.status = "captured"
        self.ledger.append(authorization)
        return authorization

    def get(self, authorization_id: str) -> Authorization | None:
        return self._authorizations.get(authorization_id)

    def refund(self, *, authorization_id: str, credential: AIBankCredential) -> Authorization:
        """Reembolso total. Solo la cuenta que recibió el pago (`pay_to`)
        puede reembolsarlo -- como pediría cualquier vendedor real."""
        self._check_auth(credential)
        authorization = self._authorizations.get(authorization_id)
        if authorization is None:
            raise AIBankError("authorization_not_found")
        if authorization.pay_to_account_id != credential.account_id:
            raise AIBankError("only_the_payee_can_refund")
        if authorization.status != "captured":
            raise AIBankError(f"cannot_refund_from_status_{authorization.status}")

        self._balances[authorization.pay_to_account_id] -= authorization.amount
        self._balances[authorization.payer_account_id] += authorization.amount
        authorization.status = "refunded"
        return authorization
