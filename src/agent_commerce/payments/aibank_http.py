"""Cliente HTTP de AIBank (hoy **Aerarium**): `AIBankApi` y `HolderChannel`
contra la API real (sandbox o producción), con el contrato de
`contracts/openapi/mercatus-v1.yaml` en Root1V/aerarium-agentic-banking.

Lo que este módulo resuelve y el puerto no ve:

- **Token de la integración** (`POST /oauth/token`, `client_credentials`):
  se cachea y se renueva un minuto antes de vencer. Un `401` con el token en
  caché se reintenta UNA vez con uno nuevo (doc 11 §3: "token expirado" es la
  señal de pedir otro, no de revisar credenciales).
- **Reintentos**: solo `429` y `503` (doc 11 §7), respetando `Retry-After`,
  y SIEMPRE con la misma `Idempotency-Key` -- que es lo que hace seguro
  reintentar: el banco no duplica nada. Todo lo demás es definitivo.
- **Identificadores**: todo `account_id` que llega de la API de socio tiene
  que tener prefijo `acc_`. El canal del titular usa otro espacio (UUID) y no
  pasa por esa validación (AE-06).
- **Códigos renombrados** (`LEGACY_CODE_RENAMES`): se traducen al nombre
  vigente, para que nada aguas arriba dependa de qué versión del banco
  respondió (AE-08, PR #12).

La captura devuelve solo `{authorization_id, status, settled_at}`; para
devolver una `Authorization` completa se consulta después con `GET`. Ojo con
un caso fino (AE-08): un reintento de captura que recibe
`authorization_not_capturable` sobre algo que el `GET` muestra `refunded` o
`partially_refunded` significa que la captura original SÍ se hizo.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from .aibank_api import (
    LEGACY_CODE_RENAMES,
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

_TOKEN_REFRESH_MARGIN_SECONDS = 60
_MAX_RETRY_AFTER_SECONDS = 30
_DEFAULT_TIMEOUT = httpx.Timeout(10.0)


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _required_dt(value: str) -> datetime:
    parsed = _parse_dt(value)
    assert parsed is not None
    return parsed


def _partner_account_id(value: Any) -> str:
    """La API de socio solo expone ids opacos con prefijo (AE-06)."""
    if not isinstance(value, str) or not value.startswith("acc_"):
        raise AIBankError("server_error", f"la API devolvió un account_id inesperado: {value!r}")
    return value


def _error_from_response(response: httpx.Response) -> AIBankError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    # La API de socio responde `{"error": ...}`; el canal del titular (BFF),
    # `{"code": ...}`. Mismo significado, distinta clave.
    code = (body.get("error") or body.get("code")) if isinstance(body, dict) else None
    message = (body.get("message") or body.get("error_description") or "") if isinstance(body, dict) else ""
    if not code:
        code = {401: "invalid_credential", 429: "rate_limited", 503: "service_unavailable"}.get(
            response.status_code, "server_error"
        )
    if code == "invalid_client":  # RFC 6749 §5.2, desde /oauth/token
        code = "invalid_credential"
    code = LEGACY_CODE_RENAMES.get(code, code)
    retry_after = response.headers.get("Retry-After")
    return AIBankError(
        code,
        message or f"HTTP {response.status_code}",
        retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
    )


def _mandate_from_json(data: dict[str, Any], *, account_id: str) -> Mandate:
    return Mandate(
        mandate_id=data["mandate_id"],
        account_id=account_id,
        currency=data["currency"],
        status=data["status"],
        max_per_operation=data.get("max_per_operation"),
        max_total=data.get("max_total"),
        consumed=data.get("consumed", 0),
        remaining=data.get("remaining"),
        expires_at=_required_dt(data["expires_at"]),
        revoked_at=_parse_dt(data.get("revoked_at")),
    )


class AIBankHttpApi(AIBankApi):
    """La API de socio autenticada como una integración (`client_id`/`client_secret`)."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        http: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._injected_http = http
        self._max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._token: str | None = None
        self._token_valid_until = 0.0
        # Un cliente HTTP y un lock POR event loop: el vendedor (servidor
        # uvicorn en su propio hilo, en la demo y en el dashboard) y el
        # comprador comparten esta instancia, y un `AsyncClient`/`Lock` queda
        # atado al loop en que se creó. El token sí se comparte.
        self._per_loop: dict[asyncio.AbstractEventLoop, tuple[httpx.AsyncClient, asyncio.Lock]] = {}

    def _loop_state(self) -> tuple[httpx.AsyncClient, asyncio.Lock]:
        loop = asyncio.get_running_loop()
        state = self._per_loop.get(loop)
        if state is None:
            state = (self._injected_http or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT), asyncio.Lock())
            self._per_loop[loop] = state
        return state

    async def aclose(self) -> None:
        """Cierra el cliente del event loop actual."""
        state = self._per_loop.pop(asyncio.get_running_loop(), None)
        if state is not None:
            await state[0].aclose()

    # --- Transporte ------------------------------------------------------

    def _token_form(self) -> dict[str, str]:
        return {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

    def _remember_token(self, response: httpx.Response) -> str:
        if not response.is_success:
            raise _error_from_response(response)
        body = response.json()
        token: str = body["access_token"]
        self._token = token
        self._token_valid_until = self._clock() + int(body.get("expires_in", 3600)) - _TOKEN_REFRESH_MARGIN_SECONDS
        return token

    async def _access_token(self, *, force_refresh: bool = False) -> str:
        http, lock = self._loop_state()
        async with lock:
            if self._token and not force_refresh and self._clock() < self._token_valid_until:
                return self._token
            response = await http.post(f"{self._base_url}/oauth/token", data=self._token_form())
            return self._remember_token(response)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        refreshed = False
        attempt = 0
        while True:
            token = await self._access_token()
            http, _ = self._loop_state()
            response = await http.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {token}", **(headers or {})},
            )
            if response.status_code == 401 and not refreshed:
                refreshed = True
                await self._access_token(force_refresh=True)
                continue
            if response.status_code in (429, 503) and attempt < self._max_retries:
                attempt += 1
                error = _error_from_response(response)
                await self._sleep(min(error.retry_after or attempt, _MAX_RETRY_AFTER_SECONDS))
                continue
            if response.is_success:
                return response
            raise _error_from_response(response)

    # --- Cuentas ---------------------------------------------------------

    def open_account_blocking(
        self, *, owner_reference: str, currency: str = "USD", initial_balance: int | None = None
    ) -> Account:
        """`open_account` síncrono, para sembrar cuentas al arrancar (CLI,
        dashboard) antes de que haya un event loop. Idempotente igual."""
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            token = self._remember_token(client.post(f"{self._base_url}/oauth/token", data=self._token_form()))
            response = client.post(
                f"{self._base_url}/v1/accounts",
                json=self._account_body(owner_reference, currency, None, initial_balance),
                headers={"Authorization": f"Bearer {token}"},
            )
        if not response.is_success:
            raise _error_from_response(response)
        return self._account_from(response.json())

    @staticmethod
    def _account_body(
        owner_reference: str, currency: str, display_name: str | None, initial_balance: int | None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"owner_reference": owner_reference, "currency": currency}
        if display_name is not None:
            body["display_name"] = display_name
        if initial_balance is not None:
            body["initial_balance"] = initial_balance
        return body

    @staticmethod
    def _account_from(data: dict[str, Any]) -> Account:
        return Account(
            account_id=_partner_account_id(data["account_id"]), currency=data["currency"], status=data["status"]
        )

    async def open_account(
        self,
        *,
        owner_reference: str,
        currency: str = "USD",
        display_name: str | None = None,
        initial_balance: int | None = None,
    ) -> Account:
        response = await self._request(
            "POST", "/v1/accounts", json=self._account_body(owner_reference, currency, display_name, initial_balance)
        )
        return self._account_from(response.json())

    # --- Pagos -----------------------------------------------------------

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
        if not idempotency_key:
            # El banco lo rechaza igual (`400`); fallar antes ahorra la llamada.
            raise AIBankError("malformed_request", "falta el encabezado Idempotency-Key")
        body: dict[str, Any] = {
            "payer_account_id": payer_account_id,
            "payee_account_id": payee_account_id,
            "amount": amount,
            "currency": currency,
        }
        if mandate_id is not None:
            body["mandate_id"] = mandate_id
        response = await self._request(
            "POST", "/v1/authorizations", json=body, headers={"Idempotency-Key": idempotency_key}
        )
        data = response.json()
        return Authorization(
            authorization_id=data["authorization_id"],
            status=data["status"],
            payer_account_id=payer_account_id,
            payee_account_id=payee_account_id,
            amount=amount,
            currency=currency,
            expires_at=_required_dt(data["expires_at"]),
            settled_at=_parse_dt(data.get("settled_at")),
            replayed=response.status_code == 200 and response.headers.get("Idempotent-Replay") == "true",
        )

    async def capture(self, authorization_id: str) -> Authorization:
        await self._request("POST", f"/v1/authorizations/{authorization_id}/capture")
        return await self.get_authorization(authorization_id)

    async def get_authorization(
        self,
        authorization_id: str,
        *,
        expected_amount: int | None = None,
        expected_payee_account_id: str | None = None,
    ) -> Authorization:
        params: dict[str, Any] = {}
        if expected_amount is not None:
            params["expected_amount"] = expected_amount
        if expected_payee_account_id is not None:
            params["expected_payee_account_id"] = expected_payee_account_id
        data = (await self._request("GET", f"/v1/authorizations/{authorization_id}", params=params)).json()
        return Authorization(
            authorization_id=data["authorization_id"],
            status=data["status"],
            payer_account_id=_partner_account_id(data["payer_account_id"]),
            payee_account_id=_partner_account_id(data["payee_account_id"]),
            amount=data["amount"],
            currency=data["currency"],
            expires_at=_required_dt(data["expires_at"]),
            settled_at=_parse_dt(data.get("settled_at")),
        )

    async def refund(self, authorization_id: str, *, amount: int | None = None) -> Refund:
        data = (
            await self._request(
                "POST", f"/v1/authorizations/{authorization_id}/refund", json={"amount": amount} if amount else None
            )
        ).json()
        return Refund(
            authorization_id=data["authorization_id"],
            status=data["status"],
            refunded=data["refunded"],
            refunded_total=data["refunded_total"],
            refundable=data["refundable"],
            currency=data["currency"],
        )

    # --- Modelo B --------------------------------------------------------

    async def create_consent_request(
        self,
        *,
        purpose: str,
        currency: str = "USD",
        max_per_operation: int | None = None,
        max_total: int | None = None,
    ) -> ConsentRequest:
        body: dict[str, Any] = {"currency": currency, "purpose": purpose}
        if max_per_operation is not None:
            body["max_per_operation"] = max_per_operation
        if max_total is not None:
            body["max_total"] = max_total
        return self._consent_from((await self._request("POST", "/v1/consent-requests", json=body)).json())

    async def get_consent_request(self, consent_request_id: str) -> ConsentRequest:
        return self._consent_from((await self._request("GET", f"/v1/consent-requests/{consent_request_id}")).json())

    @staticmethod
    def _consent_from(data: dict[str, Any]) -> ConsentRequest:
        account_id = data.get("account_id")
        return ConsentRequest(
            consent_request_id=data["consent_request_id"],
            handoff_code=data["handoff_code"],
            status=data["status"],
            expires_at=_required_dt(data["expires_at"]),
            mandate_id=data.get("mandate_id"),
            account_id=_partner_account_id(account_id) if account_id else None,
        )

    async def get_mandate(self, mandate_id: str) -> Mandate:
        data = (await self._request("GET", f"/v1/mandates/{mandate_id}")).json()
        return _mandate_from_json(data, account_id=_partner_account_id(data["account_id"]))


class AIBankHttpHolderChannel(HolderChannel):
    """El canal del titular del sandbox (`POST /dev/holders` + rutas del BFF).
    Solo existe en el sandbox: en producción esto lo hace una persona en la
    app del banco. Sus ids de cuenta son del espacio del titular (UUID), y no
    se validan como `acc_` (AE-06)."""

    def __init__(self, *, base_url: str, dev_key: str | None = None, http: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._dev_key = dev_key
        self._injected_http = http

    async def aclose(self) -> None:
        """Nada que cerrar: sin cliente inyectado se usa uno por llamada (este
        canal es de muy poco tráfico y así no queda atado a un event loop)."""

    async def _post(self, path: str, *, json: dict[str, Any] | None = None, headers: dict[str, str]) -> httpx.Response:
        url = f"{self._base_url}{path}"
        if self._injected_http is not None:
            response = await self._injected_http.post(url, json=json, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as http:
                response = await http.post(url, json=json, headers=headers)
        if not response.is_success:
            error = _error_from_response(response)
            # Los errores de `/dev/*` no traen código estable; el resto del BFF sí.
            raise error if error.code != "server_error" else AIBankError("invalid_request", error.message)
        return response

    async def create_test_holder(self, *, name: str, currency: str = "USD", initial_balance: int = 0) -> TestHolder:
        headers = {"X-Dev-Key": self._dev_key} if self._dev_key else {}
        data = (
            await self._post(
                "/dev/holders",
                json={"currency": currency, "name": name, "initial_balance": initial_balance},
                headers=headers,
            )
        ).json()
        return TestHolder(customer_id=data["customer_id"], account_id=data["account_id"], token=data["token"])

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
        body: dict[str, Any] = {"account_id": account_id, "expires_in_days": expires_in_days}
        if max_per_operation is not None:
            body["max_per_operation"] = max_per_operation
        if max_total is not None:
            body["max_total"] = max_total
        data = (
            await self._post(
                f"/v1/consent-requests/{handoff_code}/approve",
                json=body,
                headers={"Authorization": f"Bearer {holder.token}"},
            )
        ).json()
        return _mandate_from_json(data, account_id=data["account_id"])

    async def reject(self, holder: TestHolder, handoff_code: str) -> None:
        await self._post(
            f"/v1/consent-requests/{handoff_code}/reject", headers={"Authorization": f"Bearer {holder.token}"}
        )

    async def revoke(self, holder: TestHolder, mandate_id: str) -> None:
        await self._post(f"/v1/mandates/{mandate_id}/revoke", headers={"Authorization": f"Bearer {holder.token}"})
