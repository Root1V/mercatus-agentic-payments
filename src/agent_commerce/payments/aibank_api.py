"""Puerto de AIBank (hoy **Aerarium**): la API de socio tal como la ve Mercatus.

Una sola interfaz, dos implementaciones: `MockAIBank` (en memoria, para
tests/CLI/dashboard en modo mock) y el cliente HTTP contra el sandbox real
(pendiente, RM-18). La forma de cada método copia el contrato real
(`contracts/openapi/mercatus-v1.yaml` en Root1V/aerarium-agentic-banking) y,
donde los docs no alcanzan, el comportamiento de su código Go
(`services/mercatus/handlers.go`). Por eso:

- **Quien se autentica es la integración, no el agente.** Un token OAuth2
  `client_credentials` por plataforma; cada instancia de `AIBankApi` ya actúa
  en nombre de UNA integración. Un agente no tiene secreto propio: es solo
  una `account_id`, y lo que lo limita son los topes de su cuenta (AE-02).
- **La cuenta pagadora va en el cuerpo** (`payer_account_id`), en los dos
  modelos. `mandate_id` presente = modelo B (doc 13 §1).
- **Montos en micras enteras** (10⁻⁶ USD): `1000` son $0.001. Convertir con
  `usd_to_micros`, que rechaza -- nunca redondea -- más de seis decimales.
- **Errores por código estable** (`AIBankError.code`), con el mismo
  vocabulario que la API real (doc 11 §7 + doc 13 §5): una rama que dependa
  de un código que el banco no emite nunca se ejecutaría en producción (AE-03).

`HolderChannel` es aparte a propósito: es el lado del TITULAR (la app del
banco, autenticado con su dispositivo), que Mercatus nunca opera en
producción. Existe solo para poder probar el modelo B -- en el sandbox real
son `POST /dev/holders` y las rutas del BFF, con su propio vocabulario.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

MICROS_PER_USD = 1_000_000

SCOPE_PAYMENTS_READ = "payments:read"
SCOPE_PAYMENTS_WRITE = "payments:write"
SCOPE_ACCOUNTS_WRITE = "accounts:write"
ALL_SCOPES = frozenset({SCOPE_PAYMENTS_READ, SCOPE_PAYMENTS_WRITE, SCOPE_ACCOUNTS_WRITE})

# Código HTTP de cada `error` de la API de socio (doc 11 §7, doc 13 §5 y
# `services/mercatus/errors.go`). `already_captured` existe en `errors.go`
# pero la API nunca lo emite (capturar dos veces devuelve `200`), por eso no
# está acá.
HTTP_STATUS_BY_CODE: dict[str, int] = {
    "malformed_request": 400,
    "invalid_credential": 401,
    "insufficient_funds": 402,
    "insufficient_scope": 403,
    "account_frozen": 403,
    "mandate_revoked": 403,
    "mandate_expired": 403,
    "mandate_account_not_covered": 403,
    "account_not_found": 404,
    "authorization_not_found": 404,
    "consent_request_not_found": 404,
    "mandate_not_found": 404,
    "idempotency_key_reused": 409,
    "authorization_expired": 409,
    # AE-08: capturar algo que ya no está vivo (liberado, o cobrado y devuelto).
    # Antes se llamaba `already_refunded` -- ver `LEGACY_CODE_RENAMES`.
    "authorization_not_capturable": 409,
    "nothing_to_refund": 409,
    "consent_request_already_resolved": 409,
    "amount_mismatch": 422,
    "recipient_mismatch": 422,
    "currency_mismatch": 422,
    "same_account": 422,
    "refund_exceeds_capture": 422,
    "mandate_limit_exceeded": 422,
    "rate_limited": 429,
    "server_error": 500,
    "service_unavailable": 503,
}

# Códigos que la API renombró: el cliente HTTP traduce el viejo al nuevo para
# que nada aguas arriba dependa de cuál de las dos versiones del banco respondió.
LEGACY_CODE_RENAMES: dict[str, str] = {
    # PR #12 de Aerarium (AE-08): decía "reembolsado" de pagos que solo vencieron.
    "already_refunded": "authorization_not_capturable",
}

# Solo estos dos son reintentables (doc 11 §7): todo lo demás es definitivo.
RETRYABLE_CODES = frozenset({"rate_limited", "service_unavailable"})

# Vocabulario del canal del titular (BFF de Aerarium, `services/bff/consent.go`),
# distinto del de la API de socio porque es otra API, para otra persona.
HOLDER_STATUS_BY_CODE: dict[str, int] = {
    "invalid_request": 400,
    "not_found": 404,
    "already_resolved": 409,
    "expired": 409,
    "limit_above_requested": 422,
}


class AIBankError(Exception):
    """Rechazo del banco. `str(exc)` es el código estable -- compararlo por
    igualdad; `message` es para humanos y puede cambiar (doc 11 §7)."""

    def __init__(self, code: str, message: str = "", *, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message or code
        self.retry_after = retry_after

    @property
    def status(self) -> int:
        return HTTP_STATUS_BY_CODE.get(self.code) or HOLDER_STATUS_BY_CODE.get(self.code, 500)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES


def usd_to_micros(value: Decimal | str) -> int:
    """`Decimal("0.001")` -> `1000`. Rechaza con `ValueError` lo que no sea un
    monto exacto en micras: redondear en silencio es perder o inventar dinero
    justo en los precios de $0.001 que motivaron la escala (AE-02)."""
    try:
        amount = Decimal(str(value).strip().lstrip("$"))
    except InvalidOperation as exc:
        raise ValueError(f"monto inválido: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"monto inválido: {value!r}")
    micros = amount * MICROS_PER_USD
    if micros != micros.to_integral_value():
        raise ValueError(f"{value!r} tiene más de seis decimales: no es expresable en micras")
    return int(micros)


def micros_to_usd(micros: int) -> Decimal:
    """`1000` -> `Decimal("0.001")`, exacto (sin pasar por float) y sin
    notación exponencial (`10000000` -> `Decimal("10")`, no `1E+1`)."""
    value = Decimal(micros).scaleb(-6).normalize()
    return value.quantize(Decimal(1)) if value == value.to_integral_value() else value


@dataclass(frozen=True)
class Account:
    account_id: str
    currency: str
    status: str  # "active" (la API no expone otro estado al abrir)


@dataclass(frozen=True)
class Authorization:
    """`POST /v1/authorizations` + `GET /v1/authorizations/{id}` en un solo
    tipo: el detalle (cuentas, monto) lo conoce quien autorizó aunque la
    respuesta de `authorize` no lo repita."""

    authorization_id: str
    status: str  # authorized | captured | partially_refunded | refunded | released | expired
    payer_account_id: str
    payee_account_id: str
    amount: int
    currency: str
    expires_at: datetime
    settled_at: datetime | None = None
    # `True` cuando la API respondió `200 Idempotent-Replay` en vez de `201`.
    replayed: bool = False


@dataclass(frozen=True)
class Refund:
    authorization_id: str
    status: str
    refunded: int  # devuelto en ESTA operación
    refunded_total: int
    refundable: int  # lo que queda por devolver
    currency: str


@dataclass(frozen=True)
class ConsentRequest:
    consent_request_id: str
    handoff_code: str
    status: str  # pending | approved | rejected | expired
    expires_at: datetime
    mandate_id: str | None = None  # solo si approved
    account_id: str | None = None  # la que eligió el titular, solo si approved


@dataclass(frozen=True)
class Mandate:
    mandate_id: str
    account_id: str
    currency: str
    status: str  # active | revoked | expired
    max_per_operation: int | None
    max_total: int | None
    consumed: int  # incluye las retenciones vivas
    remaining: int | None  # None si no hay tope total
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class TestHolder:
    """Un titular de prueba del canal del titular (`POST /dev/holders`): su
    cuenta y la sesión con la que "abre la app" para aprobar o revocar.

    `account_id` es del espacio de identificadores del CANAL DEL TITULAR (un
    UUID), no `acc_...`: son dos canales con dos espacios de ids, y no se pasa
    nunca uno al otro (AE-06). Mercatus aprende el `acc_` de esa cuenta donde
    corresponde: en `get_consent_request` una vez aprobada."""

    __test__ = False  # no es una clase de test de pytest

    customer_id: str
    account_id: str
    token: str


class AIBankApi(ABC):
    """La API de socio, autenticada como UNA integración."""

    @abstractmethod
    async def open_account(
        self,
        *,
        owner_reference: str,
        currency: str = "USD",
        display_name: str | None = None,
        initial_balance: int | None = None,
    ) -> Account:
        """Idempotente por `(owner_reference, currency)`. `initial_balance`
        solo existe en el sandbox."""

    @abstractmethod
    async def authorize(
        self,
        *,
        payer_account_id: str,
        payee_account_id: str,
        amount: int,
        idempotency_key: str,
        currency: str = "USD",
        mandate_id: str | None = None,
    ) -> Authorization: ...

    @abstractmethod
    async def capture(self, authorization_id: str) -> Authorization:
        """Idempotente: capturar dos veces devuelve la misma captura."""

    @abstractmethod
    async def get_authorization(
        self,
        authorization_id: str,
        *,
        expected_amount: int | None = None,
        expected_payee_account_id: str | None = None,
    ) -> Authorization:
        """La verificación del vendedor: con `expected_*` el banco compara y
        responde `amount_mismatch`/`recipient_mismatch`."""

    @abstractmethod
    async def refund(self, authorization_id: str, *, amount: int | None = None) -> Refund:
        """Sin `amount` (o `0`) devuelve todo lo que quede por devolver."""

    @abstractmethod
    async def create_consent_request(
        self,
        *,
        purpose: str,
        currency: str = "USD",
        max_per_operation: int | None = None,
        max_total: int | None = None,
    ) -> ConsentRequest:
        """Modelo B, paso 1: sin cuenta -- la elige el titular."""

    @abstractmethod
    async def get_consent_request(self, consent_request_id: str) -> ConsentRequest:
        """Se consulta, no se notifica: polling hasta que deje de ser `pending`."""

    @abstractmethod
    async def get_mandate(self, mandate_id: str) -> Mandate: ...


class HolderChannel(ABC):
    """El lado del titular: solo sandbox. En producción esto lo hace una
    persona en la app del banco, con su propio dispositivo."""

    @abstractmethod
    async def create_test_holder(
        self, *, name: str, currency: str = "USD", initial_balance: int = 0
    ) -> TestHolder: ...

    @abstractmethod
    async def approve(
        self,
        holder: TestHolder,
        handoff_code: str,
        *,
        account_id: str,
        max_per_operation: int | None,
        max_total: int | None,
        expires_in_days: int = 30,
    ) -> Mandate:
        """Igual que el BFF real: `None` en un tope que se pidió significa
        "sin tope", que EXCEDE lo pedido (`limit_above_requested`). Para
        conceder exactamente lo pedido hay que repetir el valor."""

    @abstractmethod
    async def reject(self, holder: TestHolder, handoff_code: str) -> None: ...

    @abstractmethod
    async def revoke(self, holder: TestHolder, mandate_id: str) -> None: ...
