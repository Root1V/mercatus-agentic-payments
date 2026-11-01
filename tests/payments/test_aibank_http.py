"""El transporte del cliente HTTP de AIBank (`payments/aibank_http.py`): lo que
los tests de contrato no ejercitan porque el banco real no lo provoca a
pedido -- token vencido, cuota superada, respuestas malformadas, códigos
renombrados. Contra un `httpx.MockTransport`, sin red."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from agent_commerce.payments.aibank_api import AIBankError, Intent
from agent_commerce.payments.aibank_http import AIBankHttpApi
from agent_commerce.payments.aibank_signing import (
    AgentIdentity,
    generate_agent_key,
    public_jwk,
    public_key_from_jwk,
    verify_request,
)

_AUTH_RESPONSE = {
    "authorization_id": "auth_" + "a" * 32,
    "status": "authorized",
    "expires_at": "2026-09-01T16:52:07.47762Z",
}


def _api(handler: Callable[[httpx.Request], httpx.Response], sleeps: list[float] | None = None) -> AIBankHttpApi:
    async def fake_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return AIBankHttpApi(
        base_url="http://banco.test",
        client_id="mercatus",
        client_secret="secreto",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=fake_sleep,
    )


def _token(request: httpx.Request, issued: list[str]) -> httpx.Response:
    issued.append(f"tok-{len(issued) + 1}")
    return httpx.Response(200, json={"access_token": issued[-1], "expires_in": 3600})


_AGENT = AgentIdentity(agent_id="agt_" + "a" * 32, key_id="key_" + "b" * 32, private_key=generate_agent_key())


async def _authorize(api: AIBankHttpApi):
    return await api.authorize(
        payer_account_id="acc_" + "1" * 32,
        payee_account_id="acc_" + "2" * 32,
        amount=1_000,
        idempotency_key="cart_1",
        agent=_AGENT,
        intent=Intent(reference="task-1", description="Text Summarizer: resumen"),
    )


async def test_the_token_is_cached_between_calls() -> None:
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, issued)
        return httpx.Response(201, json=_AUTH_RESPONSE)

    api = _api(handler)
    await _authorize(api)
    await _authorize(api)
    assert issued == ["tok-1"]


async def test_an_expired_token_is_renewed_once_and_the_call_retried() -> None:
    issued: list[str] = []
    seen_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, issued)
        seen_tokens.append(request.headers["Authorization"])
        if len(seen_tokens) == 1:
            return httpx.Response(401, json={"error": "invalid_credential", "message": "token expirado"})
        return httpx.Response(201, json=_AUTH_RESPONSE)

    authorization = await _authorize(_api(handler))
    assert authorization.status == "authorized"
    assert seen_tokens == ["Bearer tok-1", "Bearer tok-2"]


async def test_bad_credentials_fail_without_looping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    with pytest.raises(AIBankError) as excinfo:
        await _authorize(_api(handler))
    assert excinfo.value.code == "invalid_credential"


async def test_rate_limited_is_retried_with_the_same_idempotency_key() -> None:
    keys: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, [])
        keys.append(request.headers["Idempotency-Key"])
        if len(keys) < 3:
            return httpx.Response(429, json={"error": "rate_limited"}, headers={"Retry-After": "2"})
        return httpx.Response(201, json=_AUTH_RESPONSE)

    await _authorize(_api(handler, sleeps))
    assert keys == ["cart_1", "cart_1", "cart_1"]
    assert sleeps == [2, 2]


async def test_retries_give_up_after_the_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, [])
        return httpx.Response(503, json={"error": "service_unavailable", "message": "reintenta"})

    with pytest.raises(AIBankError) as excinfo:
        await _authorize(_api(handler))
    assert excinfo.value.code == "service_unavailable"
    assert excinfo.value.retryable


async def test_definitive_errors_are_not_retried() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, [])
        calls.append(request.url.path)
        return httpx.Response(402, json={"error": "insufficient_funds", "message": "sin saldo"})

    with pytest.raises(AIBankError) as excinfo:
        await _authorize(_api(handler))
    assert (excinfo.value.code, excinfo.value.status) == ("insufficient_funds", 402)
    assert calls == ["/v1/authorizations"]


async def test_a_replayed_authorization_is_flagged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, [])
        return httpx.Response(200, json=_AUTH_RESPONSE, headers={"Idempotent-Replay": "true"})

    assert (await _authorize(_api(handler))).replayed


async def test_the_legacy_already_refunded_code_is_translated() -> None:
    """AE-08: hasta que el sandbox tenga el PR #12, el banco todavía dice
    `already_refunded`; nada aguas arriba depende del nombre viejo."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, [])
        return httpx.Response(409, json={"error": "already_refunded", "message": "ya no admite captura"})

    with pytest.raises(AIBankError) as excinfo:
        await _api(handler).capture("auth_" + "a" * 32)
    assert excinfo.value.code == "authorization_not_capturable"


async def test_partner_api_account_ids_must_carry_the_acc_prefix() -> None:
    """AE-06: un id del canal del titular (UUID) nunca debería llegar por la
    API de socio; si llega, es un error del banco, no un dato válido."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, [])
        return httpx.Response(201, json={"account_id": "75996cb7-5b8d-4f6d-9d5c-5e724f109145", "currency": "USD", "status": "active"})

    with pytest.raises(AIBankError) as excinfo:
        await _api(handler).open_account(owner_reference="agent-1")
    assert excinfo.value.code == "server_error"


async def test_a_refund_without_amount_sends_no_body() -> None:
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, [])
        bodies.append(request.content)
        return httpx.Response(
            200,
            json={
                "authorization_id": "auth_" + "a" * 32,
                "status": "refunded",
                "refunded": 1_000,
                "refunded_total": 1_000,
                "refundable": 0,
                "currency": "USD",
            },
        )

    api = _api(handler)
    await api.refund("auth_" + "a" * 32)
    await api.refund("auth_" + "a" * 32, amount=300)
    assert bodies[0] == b""
    assert json.loads(bodies[1]) == {"amount": 300}


async def test_each_attempt_is_signed_over_the_exact_body() -> None:
    """La firma cubre el cuerpo exacto que viaja (RFC 9421 + `Content-Digest`)
    y se recalcula en cada reintento -- `created` vence a los 5 minutos --,
    siempre con la misma `Idempotency-Key`."""
    public_key = public_key_from_jwk(public_jwk(_AGENT.private_key))
    verified: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token(request, [])
        key_id = verify_request("POST", request.url.path, request.content, dict(request.headers), lambda _: public_key)
        verified.append((key_id, request.headers["Idempotency-Key"]))
        assert json.loads(request.content)["agent_id"] == _AGENT.agent_id
        if len(verified) == 1:
            return httpx.Response(503, json={"error": "service_unavailable"})
        return httpx.Response(201, json=_AUTH_RESPONSE)

    await _authorize(_api(handler))
    assert verified == [(_AGENT.key_id, "cart_1")] * 2
