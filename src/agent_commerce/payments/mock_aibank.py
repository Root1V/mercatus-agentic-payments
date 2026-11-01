"""AIBank (hoy **Aerarium**) 100% en memoria, sin red ni fondos reales (RM-18).

Implementa `AIBankApi`/`HolderChannel` (`aibank_api.py`) imitando a la API
real -- no a una idea de ella: cuando el contrato
(`contracts/openapi/mercatus-v1.yaml`) no alcanza, el comportamiento sale de
su código (`services/mercatus/handlers.go`, `services/bff/consent.go` y
`services/oauth/consent.go` en Root1V/aerarium-agentic-banking, `86731d1`).
Lo que eso fija, y que una versión anterior de este mock simplificaba:

- **Se autentica la integración** (`register_integration` → `client`), no
  cada cuenta: una clave por cuenta daría `401` en la primera llamada real
  (AE-02).
- **Visibilidad**: el receptor de un pago SIEMPRE es una cuenta de la
  integración (también en el modelo B: un mandato autoriza a sacar dinero de
  la cuenta del titular, nunca a elegir dónde termina). Una autorización es
  operable si cualquiera de sus dos cuentas es de la integración. Lo ajeno
  responde igual que lo inexistente (`account_not_found`,
  `authorization_not_found`, `mandate_not_found`): no se puede confirmar que
  algo de otra integración existe.
- **Retener al autorizar**: el dinero sale del saldo disponible del pagador
  en `authorize`, no en `capture`; una retención vencida vuelve sola (en el
  banco real lo hace el "barrendero"; acá, perezosamente, en cada operación).
- **Montos en micras enteras** y el vocabulario de errores real (AE-03).

Lo único que este mock tiene y la API de socio no: `register_integration`,
`freeze_account`, `available_balance` y el reloj inyectable -- controles de
sandbox para que los tests puedan provocar cada escenario sin esperar 15
minutos ni depender de datos de otra corrida.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from .aibank_api import (
    ALL_SCOPES,
    SCOPE_ACCOUNTS_WRITE,
    SCOPE_PAYMENTS_READ,
    SCOPE_PAYMENTS_WRITE,
    Account,
    AIBankApi,
    AIBankError,
    Authorization,
    ConsentRequest,
    HolderChannel,
    Mandate,
    Refund,
    TestHolder,
)

# 15 minutos de vigencia de una retención (Q8, confirmado en doc 13 §1).
AUTHORIZATION_TTL_SECONDS = 900

# Una hora de vigencia de una solicitud de consentimiento sin resolver.
CONSENT_REQUEST_TTL_SECONDS = 3600

_LIVE_AUTHORIZATION_STATUSES = ("authorized", "captured", "partially_refunded")


def _to_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)


@dataclass
class _Integration:
    client_id: str
    secret: str
    scopes: frozenset[str]


@dataclass
class _Account:
    id: str
    currency: str
    balance: int  # disponible: lo retenido ya salió de acá
    status: str = "active"  # "active" | "frozen"
    owner_client_id: str | None = None  # sub-cuenta de una integración (modelo A)
    owner_customer_id: str | None = None  # cuenta de un cliente del banco (modelo B)
    owner_reference: str | None = None
    # Id de esta cuenta en el canal del titular (UUID), distinto del `acc_...`
    # de la API de socio -- igual que en Aerarium (AE-06).
    holder_ref: str | None = None


@dataclass
class _Authorization:
    id: str
    payer: str
    payee: str
    amount: int
    currency: str
    status: str
    expires_at: float
    fingerprint: tuple[str, str, int, str, str | None]
    settled_at: float | None = None
    refunded: int = 0
    mandate_id: str | None = None


@dataclass
class _ConsentRequest:
    id: str
    handoff_code: str
    client_id: str
    currency: str
    max_per_operation: int | None
    max_total: int | None
    purpose: str
    status: str  # "pending" | "approved" | "rejected" (vencida se observa por reloj)
    expires_at: float
    mandate_id: str | None = None
    account_id: str | None = None


@dataclass
class _Mandate:
    id: str
    account_id: str
    grantee: str  # client_id de la integración a la que se le concedió
    customer_id: str
    currency: str
    max_per_operation: int | None
    max_total: int | None
    status: str  # "active" | "revoked" | "expired"
    expires_at: float
    revoked_at: float | None = None


@dataclass
class _Holder:
    customer_id: str
    token: str


class MockAIBank:
    """El banco: estado compartido entre integraciones y titulares. Se opera
    a través de `client(...)` (API de socio) y `holder_channel()` (titular)."""

    def __init__(self, *, clock: Callable[[], float] = time.time, currencies: Iterable[str] = ("USD",)) -> None:
        self._clock = clock
        self._currencies = frozenset(currencies)
        self._integrations: dict[str, _Integration] = {}
        self._accounts: dict[str, _Account] = {}
        self._accounts_by_owner: dict[tuple[str, str, str], str] = {}  # (client, ref, moneda) -> id
        self._authorizations: dict[str, _Authorization] = {}
        self._idempotency: dict[str, str] = {}  # "client:clave" -> authorization_id
        self._consent_requests: dict[str, _ConsentRequest] = {}
        self._mandates: dict[str, _Mandate] = {}
        self._holders: dict[str, _Holder] = {}  # token -> titular

    # ------------------------------------------------------------------
    # Controles de sandbox (sin equivalente en la API de socio)
    # ------------------------------------------------------------------

    def register_integration(self, client_id: str, *, scopes: Iterable[str] = ALL_SCOPES) -> str:
        """El alta que en el sandbox real hace `bootstrap`: devuelve el secreto."""
        secret = secrets.token_urlsafe(32)
        self._integrations[client_id] = _Integration(client_id, secret, frozenset(scopes))
        return secret

    def client(self, client_id: str, client_secret: str) -> MockAIBankApi:
        return MockAIBankApi(self, client_id, client_secret)

    def holder_channel(self) -> MockHolderChannel:
        return MockHolderChannel(self)

    def freeze_account(self, account_id: str) -> None:
        self._accounts[account_id].status = "frozen"

    def available_balance(self, account_id: str) -> int:
        self._sweep()
        return self._accounts[account_id].balance

    def provision_account(
        self, *, client_id: str, owner_reference: str, initial_balance: int, currency: str = "USD"
    ) -> Account:
        """`open_account` síncrono, para sembrar cuentas al arrancar (CLI,
        dashboard) sin un event loop. Mismas reglas e idempotencia."""
        return self._open_account(
            client_id=client_id,
            owner_reference=owner_reference,
            currency=currency,
            initial_balance=initial_balance,
        )

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _now(self) -> float:
        return self._clock()

    def _authenticate(self, client_id: str, client_secret: str, scope: str) -> str:
        integration = self._integrations.get(client_id)
        if integration is None or not secrets.compare_digest(integration.secret, client_secret):
            raise AIBankError("invalid_credential", "token inválido")
        if scope not in integration.scopes:
            raise AIBankError("insufficient_scope", f"el token no incluye {scope}")
        return client_id

    def _sweep(self) -> None:
        """Lo que en el banco real hace el barrendero: libera las retenciones
        vencidas y marca vencidos los mandatos fuera de vigencia."""
        now = self._now()
        for authorization in self._authorizations.values():
            if authorization.status == "authorized" and now > authorization.expires_at:
                authorization.status = "expired"
                self._accounts[authorization.payer].balance += authorization.amount
        for mandate in self._mandates.values():
            if mandate.status == "active" and now > mandate.expires_at:
                mandate.status = "expired"

    def _owned_account(self, client_id: str, account_id: str | None) -> _Account:
        if not account_id:
            raise AIBankError("malformed_request", "falta el identificador de cuenta")
        account = self._accounts.get(account_id)
        if account is None or account.owner_client_id != client_id:
            raise AIBankError("account_not_found", "la cuenta no existe")
        return account

    def _owned_authorization(self, client_id: str, authorization_id: str) -> _Authorization:
        authorization = self._authorizations.get(authorization_id)
        if authorization is not None:
            for account_id in (authorization.payer, authorization.payee):
                if self._accounts[account_id].owner_client_id == client_id:
                    return authorization
        raise AIBankError("authorization_not_found", "la autorización no existe")

    def _granted_mandate(self, client_id: str, mandate_id: str) -> _Mandate:
        mandate = self._mandates.get(mandate_id)
        if mandate is None or mandate.grantee != client_id:
            raise AIBankError("mandate_not_found", "el mandato no existe")
        return mandate

    def _consumed(self, mandate_id: str) -> int:
        return sum(
            a.amount - a.refunded
            for a in self._authorizations.values()
            if a.mandate_id == mandate_id and a.status in _LIVE_AUTHORIZATION_STATUSES
        )

    def _consent_status(self, request: _ConsentRequest) -> str:
        if request.status == "pending" and self._now() > request.expires_at:
            return "expired"
        return request.status

    # --- API de socio ----------------------------------------------------

    def _open_account(
        self, *, client_id: str, owner_reference: str, currency: str, initial_balance: int | None
    ) -> Account:
        if not owner_reference:
            raise AIBankError("malformed_request", "falta owner_reference")
        if len(currency) != 3:
            raise AIBankError("malformed_request", "currency debe ser ISO-4217 de 3 letras")
        if currency not in self._currencies:
            raise AIBankError("currency_mismatch", f"{currency} no está habilitada en este entorno")
        if initial_balance is not None and initial_balance < 0:
            raise AIBankError("malformed_request", "initial_balance no puede ser negativo")

        key = (client_id, owner_reference, currency)
        existing_id = self._accounts_by_owner.get(key)
        if existing_id is None:
            account = _Account(
                id=f"acc_{uuid.uuid4().hex}",
                currency=currency,
                balance=initial_balance or 0,
                owner_client_id=client_id,
                owner_reference=owner_reference,
            )
            self._accounts[account.id] = account
            self._accounts_by_owner[key] = account.id
            existing_id = account.id
        account = self._accounts[existing_id]
        return Account(account_id=account.id, currency=account.currency, status="active")

    def _authorize(
        self,
        *,
        client_id: str,
        payer_account_id: str,
        payee_account_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        mandate_id: str | None,
    ) -> Authorization:
        # Mismo orden que `handleAuthorize`: forma de la petición, receptor
        # propio, pagador (propio o del mandato), misma cuenta, y recién
        # después las reglas del core (idempotencia, estado, saldo).
        if not idempotency_key or len(idempotency_key) > 255:
            raise AIBankError("malformed_request", "falta el encabezado Idempotency-Key")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise AIBankError("malformed_request", "amount debe ser un entero mayor que cero, en micras")
        if len(currency) != 3:
            raise AIBankError("malformed_request", "currency debe ser ISO-4217 de 3 letras")
        self._sweep()

        payee = self._owned_account(client_id, payee_account_id)
        mandate: _Mandate | None = None
        if mandate_id:
            mandate = self._granted_mandate(client_id, mandate_id)
            if payer_account_id and payer_account_id != mandate.account_id:
                raise AIBankError("mandate_account_not_covered", "el permiso no cubre la cuenta pagadora indicada")
            payer = self._accounts[mandate.account_id]
        else:
            payer = self._owned_account(client_id, payer_account_id)
        if payer.id == payee.id:
            raise AIBankError("same_account", "pagador y receptor no pueden ser la misma cuenta")

        fingerprint = (payer.id, payee.id, amount, currency, mandate_id)
        idempotency_slot = f"{client_id}:{idempotency_key}"
        existing_id = self._idempotency.get(idempotency_slot)
        if existing_id is not None:
            existing = self._authorizations[existing_id]
            if existing.fingerprint != fingerprint:
                raise AIBankError(
                    "idempotency_key_reused", "esa Idempotency-Key ya se usó con otro monto o con otras cuentas"
                )
            return self._to_authorization(existing, replayed=True)

        if payer.currency != payee.currency or payer.currency != currency:
            raise AIBankError("currency_mismatch", "pagador y receptor no comparten moneda")
        if payer.status != "active" or payee.status != "active":
            raise AIBankError("account_frozen", "la cuenta está congelada y no admite movimientos")
        if mandate is not None:
            if mandate.status == "revoked":
                raise AIBankError("mandate_revoked", "el titular retiró el permiso")
            if mandate.status == "expired":
                raise AIBankError("mandate_expired", "el permiso venció; hay que pedir uno nuevo")
            over_operation = mandate.max_per_operation is not None and amount > mandate.max_per_operation
            over_total = mandate.max_total is not None and self._consumed(mandate.id) + amount > mandate.max_total
            if over_operation or over_total:
                raise AIBankError("mandate_limit_exceeded", "el pago supera lo que el titular autorizó")
        if payer.balance < amount:
            raise AIBankError("insufficient_funds", "la cuenta pagadora no tiene saldo suficiente")

        payer.balance -= amount
        authorization = _Authorization(
            id=f"auth_{uuid.uuid4().hex}",
            payer=payer.id,
            payee=payee.id,
            amount=amount,
            currency=currency,
            status="authorized",
            expires_at=self._now() + AUTHORIZATION_TTL_SECONDS,
            fingerprint=fingerprint,
            mandate_id=mandate_id,
        )
        self._authorizations[authorization.id] = authorization
        self._idempotency[idempotency_slot] = authorization.id
        return self._to_authorization(authorization)

    def _capture(self, *, client_id: str, authorization_id: str) -> Authorization:
        authorization = self._owned_authorization(client_id, authorization_id)
        self._sweep()
        if authorization.status == "authorized":
            self._accounts[authorization.payee].balance += authorization.amount
            authorization.status = "captured"
            authorization.settled_at = self._now()
        elif authorization.status == "expired":
            raise AIBankError("authorization_expired", "la autorización venció y el dinero se devuelve al pagador")
        elif authorization.status != "captured":
            # Ya no está viva: se cobró y se devolvió (AE-08). Que el 409 no
            # engañe: si el `GET` dice `refunded`, la captura original SÍ se hizo.
            raise AIBankError("authorization_not_capturable", "la autorización ya no admite captura")
        return self._to_authorization(authorization)

    def _get_authorization(
        self,
        *,
        client_id: str,
        authorization_id: str,
        expected_amount: int | None,
        expected_payee_account_id: str | None,
    ) -> Authorization:
        authorization = self._owned_authorization(client_id, authorization_id)
        self._sweep()
        if expected_amount is not None and expected_amount != authorization.amount:
            raise AIBankError("amount_mismatch", "el monto autorizado no coincide con el esperado")
        if expected_payee_account_id is not None and expected_payee_account_id != authorization.payee:
            raise AIBankError("recipient_mismatch", "el receptor de la autorización no coincide con el esperado")
        return self._to_authorization(authorization)

    def _refund(self, *, client_id: str, authorization_id: str, amount: int | None) -> Refund:
        authorization = self._owned_authorization(client_id, authorization_id)
        if amount is not None and amount < 0:
            raise AIBankError("malformed_request", "amount no puede ser negativo")
        self._sweep()
        refundable = authorization.amount - authorization.refunded
        if authorization.status == "refunded" and not amount:
            # Repetir el reembolso de algo ya devuelto entero: `200` sin mover
            # dinero (AE-08), para que un reintento por timeout no sea un error.
            return self._to_refund(authorization, refunded=0)
        if authorization.status not in ("captured", "partially_refunded"):
            raise AIBankError("nothing_to_refund", "la autorización no tiene un cobro que devolver")
        to_refund = amount or refundable
        if to_refund > refundable:
            raise AIBankError("refund_exceeds_capture", "el reembolso supera lo que queda por devolver")
        payee = self._accounts[authorization.payee]
        if payee.balance < to_refund:
            raise AIBankError("insufficient_funds", "la cuenta receptora no tiene saldo para devolver")

        payee.balance -= to_refund
        self._accounts[authorization.payer].balance += to_refund
        authorization.refunded += to_refund
        authorization.status = "refunded" if authorization.refunded == authorization.amount else "partially_refunded"
        return self._to_refund(authorization, refunded=to_refund)

    def _create_consent_request(
        self,
        *,
        client_id: str,
        purpose: str,
        currency: str,
        max_per_operation: int | None,
        max_total: int | None,
    ) -> ConsentRequest:
        if len(currency) != 3:
            raise AIBankError("malformed_request", "currency debe ser ISO-4217 de 3 letras")
        if not purpose or len(purpose) > 500:
            raise AIBankError("malformed_request", "purpose es obligatorio: es lo que el titular lee antes de decidir")
        for name, value in (("max_per_operation", max_per_operation), ("max_total", max_total)):
            if value is not None and value <= 0:
                raise AIBankError("malformed_request", f"{name} debe ser mayor que cero")
        request = _ConsentRequest(
            id=str(uuid.uuid4()),
            handoff_code=f"csr_{secrets.token_urlsafe(32)}",
            client_id=client_id,
            currency=currency,
            max_per_operation=max_per_operation,
            max_total=max_total,
            purpose=purpose,
            status="pending",
            expires_at=self._now() + CONSENT_REQUEST_TTL_SECONDS,
        )
        self._consent_requests[request.id] = request
        return self._to_consent_request(request)

    def _get_consent_request(self, *, client_id: str, consent_request_id: str) -> ConsentRequest:
        request = self._consent_requests.get(consent_request_id)
        if request is None or request.client_id != client_id:
            raise AIBankError("consent_request_not_found", "la solicitud no existe")
        return self._to_consent_request(request)

    def _get_mandate(self, *, client_id: str, mandate_id: str) -> Mandate:
        self._sweep()
        return self._to_mandate(self._granted_mandate(client_id, mandate_id))

    # --- Canal del titular -------------------------------------------------

    def _holder(self, holder: TestHolder) -> _Holder:
        known = self._holders.get(holder.token)
        if known is None or known.customer_id != holder.customer_id:
            raise AIBankError("invalid_request", "sesión del titular inválida")
        return known

    def _pending_by_handoff(self, handoff_code: str) -> _ConsentRequest:
        request = next((r for r in self._consent_requests.values() if r.handoff_code == handoff_code), None)
        if request is None:
            raise AIBankError("not_found", "esa solicitud no existe")
        status = self._consent_status(request)
        if status == "expired":
            raise AIBankError("expired", "la solicitud venció; pide una nueva")
        if status != "pending":
            raise AIBankError("already_resolved", "esa solicitud ya fue respondida")
        return request

    def _create_test_holder(self, *, name: str, currency: str, initial_balance: int) -> TestHolder:
        if currency not in self._currencies:
            raise AIBankError("invalid_request", f"{currency} no está habilitada en este entorno")
        customer_id = str(uuid.uuid4())
        account = _Account(
            id=f"acc_{uuid.uuid4().hex}",
            currency=currency,
            balance=initial_balance,
            owner_customer_id=customer_id,
            holder_ref=str(uuid.uuid4()),
        )
        self._accounts[account.id] = account
        holder = _Holder(customer_id=customer_id, token=f"hold_{secrets.token_urlsafe(24)}")
        self._holders[holder.token] = holder
        assert account.holder_ref is not None
        return TestHolder(customer_id=customer_id, account_id=account.holder_ref, token=holder.token)

    def _approve(
        self,
        *,
        holder: TestHolder,
        handoff_code: str,
        account_id: str,
        max_per_operation: int | None,
        max_total: int | None,
        expires_in_days: int,
    ) -> Mandate:
        known = self._holder(holder)
        if not 1 <= expires_in_days <= 365:
            raise AIBankError("invalid_request", "la vigencia debe estar entre 1 y 365 días")
        request = self._pending_by_handoff(handoff_code)

        def exceeds(granted: int | None, requested: int | None) -> bool:
            # `services/oauth/consent.go`: sin tope concedido = sin tope, que
            # excede cualquier tope pedido.
            if requested is None:
                return False
            return granted is None or granted > requested

        if exceeds(max_per_operation, request.max_per_operation) or exceeds(max_total, request.max_total):
            raise AIBankError("limit_above_requested", "no puedes conceder más de lo que se te pidió")
        if any(value is not None and value <= 0 for value in (max_per_operation, max_total)):
            raise AIBankError("invalid_request", "no se puede otorgar el permiso sobre esa cuenta")
        # El titular nombra la cuenta con el id de SU canal (AE-06).
        account = next((a for a in self._accounts.values() if a.holder_ref == account_id), None)
        if account is None or account.owner_customer_id != known.customer_id:
            raise AIBankError("not_found", "esa cuenta no existe")

        mandate = _Mandate(
            id=str(uuid.uuid4()),
            account_id=account.id,
            grantee=request.client_id,
            customer_id=known.customer_id,
            currency=account.currency,
            max_per_operation=max_per_operation,
            max_total=max_total,
            status="active",
            expires_at=self._now() + expires_in_days * 86400,
        )
        self._mandates[mandate.id] = mandate
        request.status = "approved"
        request.mandate_id = mandate.id
        request.account_id = account.id
        return self._to_mandate(mandate, holder_view=True)

    def _reject(self, *, holder: TestHolder, handoff_code: str) -> None:
        self._holder(holder)
        self._pending_by_handoff(handoff_code).status = "rejected"

    def _revoke(self, *, holder: TestHolder, mandate_id: str) -> None:
        known = self._holder(holder)
        mandate = self._mandates.get(mandate_id)
        if mandate is None or mandate.customer_id != known.customer_id:
            raise AIBankError("not_found", "ese permiso no existe")
        if mandate.status == "active":
            # Las retenciones vivas NO se cancelan (doc 13 §4): del otro lado
            # puede haber un vendedor que ya entregó.
            mandate.status = "revoked"
            mandate.revoked_at = self._now()

    # --- Conversión a los tipos del puerto ---------------------------------

    def _to_authorization(self, authorization: _Authorization, *, replayed: bool = False) -> Authorization:
        return Authorization(
            authorization_id=authorization.id,
            status=authorization.status,
            payer_account_id=authorization.payer,
            payee_account_id=authorization.payee,
            amount=authorization.amount,
            currency=authorization.currency,
            expires_at=_to_datetime(authorization.expires_at),
            settled_at=_to_datetime(authorization.settled_at) if authorization.settled_at else None,
            replayed=replayed,
        )

    def _to_consent_request(self, request: _ConsentRequest) -> ConsentRequest:
        status = self._consent_status(request)
        approved = status == "approved"
        return ConsentRequest(
            consent_request_id=request.id,
            handoff_code=request.handoff_code,
            status=status,
            expires_at=_to_datetime(request.expires_at),
            mandate_id=request.mandate_id if approved else None,
            account_id=request.account_id if approved else None,
        )

    def _to_refund(self, authorization: _Authorization, *, refunded: int) -> Refund:
        return Refund(
            authorization_id=authorization.id,
            status=authorization.status,
            refunded=refunded,
            refunded_total=authorization.refunded,
            refundable=authorization.amount - authorization.refunded,
            currency=authorization.currency,
        )

    def _to_mandate(self, mandate: _Mandate, *, holder_view: bool = False) -> Mandate:
        """`holder_view`: lo que ve el titular en su canal, con el id de cuenta
        de ESE canal (UUID); la API de socio ve el `acc_...` (AE-06)."""
        consumed = self._consumed(mandate.id)
        account = self._accounts[mandate.account_id]
        return Mandate(
            mandate_id=mandate.id,
            account_id=account.holder_ref if holder_view and account.holder_ref else mandate.account_id,
            currency=mandate.currency,
            status=mandate.status,
            max_per_operation=mandate.max_per_operation,
            max_total=mandate.max_total,
            consumed=consumed,
            remaining=mandate.max_total - consumed if mandate.max_total is not None else None,
            expires_at=_to_datetime(mandate.expires_at),
            revoked_at=_to_datetime(mandate.revoked_at) if mandate.revoked_at else None,
        )


class MockAIBankApi(AIBankApi):
    """La API de socio de `MockAIBank`, autenticada como una integración:
    cada llamada verifica el secreto y el scope, como el token real."""

    def __init__(self, bank: MockAIBank, client_id: str, client_secret: str) -> None:
        self._bank = bank
        self._client_id = client_id
        self._client_secret = client_secret

    def _auth(self, scope: str) -> str:
        return self._bank._authenticate(self._client_id, self._client_secret, scope)

    async def open_account(
        self,
        *,
        owner_reference: str,
        currency: str = "USD",
        display_name: str | None = None,
        initial_balance: int | None = None,
    ) -> Account:
        return self._bank._open_account(
            client_id=self._auth(SCOPE_ACCOUNTS_WRITE),
            owner_reference=owner_reference,
            currency=currency,
            initial_balance=initial_balance,
        )

    async def authorize(
        self,
        *,
        payer_account_id: str,
        payee_account_id: str,
        amount: int,
        idempotency_key: str,
        currency: str = "USD",
        mandate_id: str | None = None,
    ) -> Authorization:
        return self._bank._authorize(
            client_id=self._auth(SCOPE_PAYMENTS_WRITE),
            payer_account_id=payer_account_id,
            payee_account_id=payee_account_id,
            amount=amount,
            currency=currency,
            idempotency_key=idempotency_key,
            mandate_id=mandate_id,
        )

    async def capture(self, authorization_id: str) -> Authorization:
        return self._bank._capture(client_id=self._auth(SCOPE_PAYMENTS_WRITE), authorization_id=authorization_id)

    async def get_authorization(
        self,
        authorization_id: str,
        *,
        expected_amount: int | None = None,
        expected_payee_account_id: str | None = None,
    ) -> Authorization:
        return self._bank._get_authorization(
            client_id=self._auth(SCOPE_PAYMENTS_READ),
            authorization_id=authorization_id,
            expected_amount=expected_amount,
            expected_payee_account_id=expected_payee_account_id,
        )

    async def refund(self, authorization_id: str, *, amount: int | None = None) -> Refund:
        return self._bank._refund(
            client_id=self._auth(SCOPE_PAYMENTS_WRITE), authorization_id=authorization_id, amount=amount
        )

    async def create_consent_request(
        self,
        *,
        purpose: str,
        currency: str = "USD",
        max_per_operation: int | None = None,
        max_total: int | None = None,
    ) -> ConsentRequest:
        return self._bank._create_consent_request(
            client_id=self._auth(SCOPE_PAYMENTS_WRITE),
            purpose=purpose,
            currency=currency,
            max_per_operation=max_per_operation,
            max_total=max_total,
        )

    async def get_consent_request(self, consent_request_id: str) -> ConsentRequest:
        return self._bank._get_consent_request(
            client_id=self._auth(SCOPE_PAYMENTS_READ), consent_request_id=consent_request_id
        )

    async def get_mandate(self, mandate_id: str) -> Mandate:
        return self._bank._get_mandate(client_id=self._auth(SCOPE_PAYMENTS_READ), mandate_id=mandate_id)


class MockHolderChannel(HolderChannel):
    """El canal del titular de `MockAIBank` (en el sandbox real: `/dev/holders`
    y las rutas del BFF)."""

    def __init__(self, bank: MockAIBank) -> None:
        self._bank = bank

    async def create_test_holder(self, *, name: str, currency: str = "USD", initial_balance: int = 0) -> TestHolder:
        return self._bank._create_test_holder(name=name, currency=currency, initial_balance=initial_balance)

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
        return self._bank._approve(
            holder=holder,
            handoff_code=handoff_code,
            account_id=account_id,
            max_per_operation=max_per_operation,
            max_total=max_total,
            expires_in_days=expires_in_days,
        )

    async def reject(self, holder: TestHolder, handoff_code: str) -> None:
        self._bank._reject(holder=holder, handoff_code=handoff_code)

    async def revoke(self, holder: TestHolder, mandate_id: str) -> None:
        self._bank._revoke(holder=holder, mandate_id=mandate_id)
