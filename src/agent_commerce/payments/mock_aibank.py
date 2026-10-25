"""AIBank 100% en memoria, sin red ni fondos reales (RM-18).

Implementa el contrato que especificó el equipo de AIBank en
`13-spec-modelos-a-y-b.md` (fuera de este repo, compartido con el usuario)
para sus dos modelos de cuenta:

- **Modelo A -- ómnibus**: el pagador es una sub-cuenta bajo el paraguas de
  Mercatus, autenticada acá con una API key por cuenta (`AIBankCredential`,
  *trust-on-first-use*, igual que `MockFacilitator` no exige "fondear" una
  dirección antes de poder pagar).
- **Modelo B -- cuenta propia**: el pagador es la cuenta de un cliente REAL
  de AIBank, y la autoridad para mover su dinero no la da una credencial que
  el agente posea, sino un **mandato** que ese cliente otorgó explícitamente
  (`request_consent` → aprobación del titular → `authorize_with_mandate`).
  Esto reflaja el contrato real: quien se autentica ante la API SIEMPRE es
  Mercatus (OAuth2 `client_credentials` a nivel de plataforma, no modelado
  acá porque este mock no expone HTTP) -- lo que cambia entre modelos es de
  qué cuenta sale la plata y bajo qué permiso, no quién llama a la API.

`capture`/`refund`/`get` son comunes a los dos modelos (mismo contrato, tal
como lo especifica el documento): por eso aceptan identificar a quien llama
por credencial (modelo A) o por `account_id` directo (modelo B, donde no
existe una credencial por cuenta).

No existe un "AIBank real" contra el cual liquidar en modo testnet (a
diferencia de x402, que sí tiene un facilitator público) -- esto es
deliberado, ver RM-18: el día que haya sandbox real (base URL + credenciales
OAuth2 del equipo de AIBank), se agrega un cliente HTTP equivalente a
`facilitator_selection.py`. Este mock es, mientras tanto, el sustituto local
de los dos modelos.
"""

from __future__ import annotations

import time
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

# 15 minutos -- valor que el propio equipo de AIBank propuso como default en
# su respuesta al contrato de integración (Q8) ante la falta de un plazo
# explícito en la v0.3, y que aquí adoptamos para que el simulador se
# comporte como lo hará el banco real: sobra margen para autorizar+capturar
# en el mismo instante (su patrón declarado, Q2) sin inmovilizar saldo
# indefinidamente si nunca se captura. Confirmado sin cambios en
# `13-spec-modelos-a-y-b.md` §1 para los dos modelos.
AUTHORIZATION_TTL_SECONDS = 900

# Una hora -- vigencia de una `ConsentRequest` sin resolver (doc 13 §3.1).
CONSENT_REQUEST_TTL_SECONDS = 3600

# 30 días -- el doc 13 no fija un default explícito para la vigencia de un
# mandato (lo elige el titular al aprobar, y solo puede acortarla, nunca
# extenderla más allá de lo pedido); el ejemplo de §3.4 muestra ~30 días
# entre `approved_at` implícito y `expires_at`, así que lo usamos como
# default razonable para el simulador cuando el test no pide uno distinto.
_MANDATE_DEFAULT_TTL_SECONDS = 30 * 24 * 3600


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
    status: str  # "authorized" | "captured" | "refunded" | "expired"
    idempotency_key: str
    expires_at: float
    mandate_id: str | None = None  # presente solo si se autorizó vía modelo B


@dataclass
class ConsentRequest:
    """Paso 1 del modelo B (doc 13 §3.1): Mercatus pide permiso sin conocer
    todavía sobre qué cuenta se va a conceder -- eso lo elige el titular."""

    id: str
    handoff_code: str
    currency: str
    max_per_operation: Decimal
    max_total: Decimal
    purpose: str
    status: str  # "pending" | "approved" | "rejected"
    expires_at: float
    mandate_id: str | None = None
    account_id: str | None = None


@dataclass
class Mandate:
    """Paso 2 del modelo B (doc 13 §3.2/§3.4): nace cuando el titular
    aprueba una `ConsentRequest`. `consumed`/`remaining` no se guardan --
    se derivan de las autorizaciones vivas, ver `MockAIBank.mandate_usage`."""

    id: str
    account_id: str
    currency: str
    max_per_operation: Decimal
    max_total: Decimal
    status: str  # "active" | "revoked" | "expired"
    expires_at: float


@dataclass
class MandateUsage:
    consumed: Decimal
    remaining: Decimal


class MockAIBank:
    """Banco en memoria: cuentas, saldos, autorizaciones, y el flujo de
    consentimiento/mandato del modelo B -- ver docstring del módulo."""

    def __init__(self) -> None:
        self._accounts: dict[str, str] = {}  # account_id -> api_key registrado (modelo A)
        self._balances: dict[str, Decimal] = {}
        self._authorizations: dict[str, Authorization] = {}
        self._idempotency: dict[tuple[str, str], str] = {}  # (account_id, key) -> authorization_id
        self._consent_requests: dict[str, ConsentRequest] = {}
        self._mandates: dict[str, Mandate] = {}
        self.ledger: list[Authorization] = []

    # ------------------------------------------------------------------
    # Modelo A -- cuenta ómnibus
    # ------------------------------------------------------------------

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
        duplicarla. Modelo A -- para el modelo B ver `authorize_with_mandate`."""
        self._check_auth(credential)

        dedupe_key = (credential.account_id, idempotency_key)
        existing_id = self._idempotency.get(dedupe_key)
        if existing_id is not None:
            return self._authorizations[existing_id]

        if pay_to_account_id == credential.account_id:
            raise AIBankError("same_account")

        if self._balances[credential.account_id] < amount:
            raise AIBankError("insufficient_funds")

        authorization = Authorization(
            id=f"auth_{uuid.uuid4().hex}",
            payer_account_id=credential.account_id,
            pay_to_account_id=pay_to_account_id,
            amount=amount,
            status="authorized",
            idempotency_key=idempotency_key,
            expires_at=time.time() + AUTHORIZATION_TTL_SECONDS,
        )
        self._authorizations[authorization.id] = authorization
        self._idempotency[dedupe_key] = authorization.id
        return authorization

    # ------------------------------------------------------------------
    # Modelo B -- pago sobre la cuenta del cliente (doc 13 §3)
    # ------------------------------------------------------------------

    def request_consent(
        self, *, currency: str, max_per_operation: Decimal, max_total: Decimal, purpose: str
    ) -> ConsentRequest:
        """Doc 13 §3.1. Nótese lo que NO recibe: ninguna cuenta -- eso lo
        elige el titular en el paso siguiente, no Mercatus."""
        if not purpose:
            raise AIBankError("malformed_request")
        request = ConsentRequest(
            id=str(uuid.uuid4()),
            handoff_code=f"csr_{uuid.uuid4().hex[:16]}",
            currency=currency,
            max_per_operation=max_per_operation,
            max_total=max_total,
            purpose=purpose,
            status="pending",
            expires_at=time.time() + CONSENT_REQUEST_TTL_SECONDS,
        )
        self._consent_requests[request.id] = request
        return request

    def get_consent_request(self, consent_request_id: str) -> ConsentRequest | None:
        return self._consent_requests.get(consent_request_id)

    def _pending_consent_request(self, consent_request_id: str) -> ConsentRequest:
        request = self._consent_requests.get(consent_request_id)
        if request is None or time.time() > request.expires_at:
            raise AIBankError("consent_request_not_found")
        if request.status != "pending":
            raise AIBankError("consent_request_already_resolved")
        return request

    def simulate_titular_approval(
        self,
        *,
        consent_request_id: str,
        account_id: str,
        max_per_operation: Decimal | None = None,
        max_total: Decimal | None = None,
        ttl_seconds: int = _MANDATE_DEFAULT_TTL_SECONDS,
    ) -> Mandate:
        """Sin equivalente en la API real que Mercatus llama -- en AIBank de
        verdad esto ocurre en SU app, con el titular autenticándose con su
        propio dispositivo (doc 13 §3.2, y el escenario que "debe fallar":
        una plataforma no puede conceder su propio permiso). Existe
        únicamente para poder probar el flujo del modelo B sin una interfaz
        de aprobación real -- lo que Mercatus haría en su lugar es hacer
        `GET /v1/consent-requests/{id}` en un loop hasta ver `approved`.

        `max_per_operation`/`max_total` permiten simular que el titular
        concede MENOS de lo pedido (doc 13 §3.2: puede bajar los topes,
        nunca subirlos); `None` concede exactamente lo pedido."""
        request = self._pending_consent_request(consent_request_id)
        granted_per_operation = request.max_per_operation if max_per_operation is None else max_per_operation
        granted_total = request.max_total if max_total is None else max_total
        if granted_per_operation > request.max_per_operation or granted_total > request.max_total:
            raise AIBankError("cannot_raise_requested_limits")
        if granted_per_operation <= 0 or granted_total <= 0:
            raise AIBankError("malformed_request")

        mandate = Mandate(
            id=str(uuid.uuid4()),
            account_id=account_id,
            currency=request.currency,
            max_per_operation=granted_per_operation,
            max_total=granted_total,
            status="active",
            expires_at=time.time() + ttl_seconds,
        )
        self._mandates[mandate.id] = mandate
        request.status = "approved"
        request.mandate_id = mandate.id
        request.account_id = account_id
        return mandate

    def simulate_titular_rejection(self, *, consent_request_id: str) -> ConsentRequest:
        """Mismo caso que `simulate_titular_approval` (sin equivalente en la
        API real), pero el titular rechaza: nunca nace el mandato (doc 13 §4)."""
        request = self._pending_consent_request(consent_request_id)
        request.status = "rejected"
        return request

    def get_mandate(self, mandate_id: str) -> Mandate | None:
        return self._mandates.get(mandate_id)

    def revoke_mandate(self, mandate_id: str) -> None:
        mandate = self._mandates.get(mandate_id)
        if mandate is None:
            raise AIBankError("mandate_not_found")
        mandate.status = "revoked"

    def mandate_usage(self, mandate_id: str) -> MandateUsage:
        """`consumed` no se lleva aparte -- se deriva de las autorizaciones
        vivas del mandato (doc 13 §3.4): una retención sin capturar ya
        consume el tope, y liberarla/reembolsarla lo devuelve solo."""
        mandate = self._mandates.get(mandate_id)
        if mandate is None:
            raise AIBankError("mandate_not_found")
        consumed = sum(
            (
                a.amount
                for a in self._authorizations.values()
                if a.mandate_id == mandate_id and a.status in ("authorized", "captured")
            ),
            Decimal(0),
        )
        return MandateUsage(consumed=consumed, remaining=mandate.max_total - consumed)

    def authorize_with_mandate(
        self,
        *,
        mandate_id: str,
        payer_account_id: str,
        pay_to_account_id: str,
        amount: Decimal,
        idempotency_key: str,
    ) -> Authorization:
        """Doc 13 §3.3: mismo contrato de `authorize`, pero la autoridad
        para mover el dinero la da el mandato -- no una credencial que el
        agente posea, porque la cuenta no es del agente ni de Mercatus."""
        mandate = self._mandates.get(mandate_id)
        if mandate is None:
            raise AIBankError("mandate_not_found")
        if mandate.status == "active" and time.time() > mandate.expires_at:
            mandate.status = "expired"
        if mandate.status != "active":
            raise AIBankError(f"mandate_{mandate.status}")
        if mandate.account_id != payer_account_id:
            raise AIBankError("mandate_account_not_covered")

        dedupe_key = (payer_account_id, idempotency_key)
        existing_id = self._idempotency.get(dedupe_key)
        if existing_id is not None:
            return self._authorizations[existing_id]

        if pay_to_account_id == payer_account_id:
            raise AIBankError("same_account")
        if amount > mandate.max_per_operation:
            raise AIBankError("mandate_limit_exceeded")
        if self.mandate_usage(mandate_id).consumed + amount > mandate.max_total:
            raise AIBankError("mandate_limit_exceeded")

        self._balances.setdefault(payer_account_id, _MOCK_STARTING_BALANCE)
        self._balances.setdefault(pay_to_account_id, Decimal(0))
        if self._balances[payer_account_id] < amount:
            raise AIBankError("insufficient_funds")

        authorization = Authorization(
            id=f"auth_{uuid.uuid4().hex}",
            payer_account_id=payer_account_id,
            pay_to_account_id=pay_to_account_id,
            amount=amount,
            status="authorized",
            idempotency_key=idempotency_key,
            expires_at=time.time() + AUTHORIZATION_TTL_SECONDS,
            mandate_id=mandate_id,
        )
        self._authorizations[authorization.id] = authorization
        self._idempotency[dedupe_key] = authorization.id
        return authorization

    # ------------------------------------------------------------------
    # Comunes a los dos modelos (doc 13 §3.3: "capture, refund y el GET
    # funcionan exactamente igual que en el modelo A")
    # ------------------------------------------------------------------

    def _resolve_caller_account(
        self, *, credential: AIBankCredential | None, account_id: str | None
    ) -> str:
        if credential is not None:
            self._check_auth(credential)
            return credential.account_id
        if account_id is not None:
            return account_id
        raise AIBankError("missing_credential")

    def capture(
        self,
        *,
        authorization_id: str,
        credential: AIBankCredential | None = None,
        payer_account_id: str | None = None,
    ) -> Authorization:
        """Efectiviza una autorización previa: mueve el saldo de verdad.
        Solo la cuenta pagadora (dueña de la autorización) puede capturarla
        -- identificada por `credential` (modelo A) o `payer_account_id`
        directo (modelo B, sin credencial por cuenta).

        Idempotente por naturaleza (Q9 de la respuesta de AIBank, RM-18): un
        segundo `capture` sobre una autorización YA capturada devuelve esa
        misma autorización en vez de fallar -- así un reintento por timeout
        de red no es indistinguible de un error real. `cannot_capture_from_
        status_*` queda reservado para capturar algo anulado/reembolsado/
        vencido, que sí es un error del llamador."""
        caller_account_id = self._resolve_caller_account(credential=credential, account_id=payer_account_id)
        authorization = self._authorizations.get(authorization_id)
        if authorization is None:
            raise AIBankError("authorization_not_found")
        if authorization.payer_account_id != caller_account_id:
            raise AIBankError("authorization_belongs_to_another_account")
        if authorization.status == "captured":
            return authorization
        if authorization.status == "authorized" and time.time() > authorization.expires_at:
            authorization.status = "expired"
            raise AIBankError("authorization_expired")
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

    def refund(
        self,
        *,
        authorization_id: str,
        credential: AIBankCredential | None = None,
        payee_account_id: str | None = None,
    ) -> Authorization:
        """Reembolso total. Solo la cuenta que recibió el pago (`pay_to`)
        puede reembolsarlo -- como pediría cualquier vendedor real. Al
        reembolsar una autorización del modelo B, el consumo del mandato
        (`mandate_usage`) se libera solo, porque se deriva del estado en
        vivo -- ver docstring de `Mandate`."""
        caller_account_id = self._resolve_caller_account(credential=credential, account_id=payee_account_id)
        authorization = self._authorizations.get(authorization_id)
        if authorization is None:
            raise AIBankError("authorization_not_found")
        if authorization.pay_to_account_id != caller_account_id:
            raise AIBankError("only_the_payee_can_refund")
        if authorization.status != "captured":
            raise AIBankError(f"cannot_refund_from_status_{authorization.status}")

        self._balances[authorization.pay_to_account_id] -= authorization.amount
        self._balances[authorization.payer_account_id] += authorization.amount
        authorization.status = "refunded"
        return authorization
