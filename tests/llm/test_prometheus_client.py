from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from agent_commerce.llm.client import LLMAuthError, LLMGatewayError, PrometheusLLMClient

AUTH_URL = "http://auth-service.test"
GATEWAY_URL = "http://gateway.test"


def _client(handler: Any) -> PrometheusLLMClient:
    transport = httpx.MockTransport(handler)
    return PrometheusLLMClient(
        auth_base_url=AUTH_URL,
        gateway_base_url=GATEWAY_URL,
        client_id="client-id",
        client_secret="client-secret",
        http_client=httpx.AsyncClient(transport=transport),
    )


def _token_response(request: httpx.Request, *, expires_in: int = 300) -> httpx.Response:
    assert request.url == f"{AUTH_URL}/oauth2/token"
    form = dict(httpx.QueryParams(request.content.decode()))
    assert form["grant_type"] == "client_credentials"
    assert form["client_id"] == "client-id"
    assert form["client_secret"] == "client-secret"
    return httpx.Response(
        200,
        json={
            "access_token": "token-abc",
            "token_type": "bearer",
            "expires_in": expires_in,
            "scope": "inference:read",
        },
    )


@pytest.mark.asyncio
async def test_chat_completion_fetches_token_then_calls_gateway() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/oauth2/token":
            return _token_response(request)
        assert request.headers["authorization"] == "Bearer token-abc"
        assert json.loads(request.content) == {
            "model": "test-model",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "hello"}}]},
        )

    client = _client(handler)
    result = await client.chat_completion(model="test-model", messages=[{"role": "user", "content": "hi"}])

    assert result["choices"][0]["message"]["content"] == "hello"
    assert calls == [f"{AUTH_URL}/oauth2/token", f"{GATEWAY_URL}/v1/chat/completions"]
    await client.aclose()


@pytest.mark.asyncio
async def test_token_is_cached_across_calls() -> None:
    token_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/oauth2/token":
            token_requests += 1
            return _token_response(request)
        return httpx.Response(200, json={"choices": []})

    client = _client(handler)
    await client.chat_completion(model="m", messages=[])
    await client.chat_completion(model="m", messages=[])

    assert token_requests == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_token_is_refreshed_once_expired() -> None:
    token_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/oauth2/token":
            token_requests += 1
            return _token_response(request, expires_in=1)
        return httpx.Response(200, json={"choices": []})

    client = _client(handler)
    await client.chat_completion(model="m", messages=[])
    await asyncio.sleep(1.1)
    await client.chat_completion(model="m", messages=[])

    assert token_requests == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_auth_error_raises_llm_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": "invalid_client", "error_description": "unknown client_id"}
        )

    client = _client(handler)
    with pytest.raises(LLMAuthError) as exc_info:
        await client.chat_completion(model="m", messages=[])

    assert exc_info.value.error == "invalid_client"
    assert exc_info.value.error_description == "unknown client_id"
    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_problem_details_error_raises_llm_gateway_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return _token_response(request)
        return httpx.Response(
            503,
            json={
                "type": "https://prometheus.internal/errors/backend-unavailable",
                "title": "Backend Unavailable",
                "status": 503,
                "detail": "no healthy backend for model 'm'",
                "instance": "/v1/chat/completions",
            },
        )

    client = _client(handler)
    with pytest.raises(LLMGatewayError) as exc_info:
        await client.chat_completion(model="m", messages=[])

    assert exc_info.value.status_code == 503
    assert exc_info.value.title == "Backend Unavailable"
    assert "no healthy backend" in (exc_info.value.detail or "")
    await client.aclose()


@pytest.mark.asyncio
async def test_list_models_does_not_require_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": "test-model", "object": "model", "owned_by": "prometheus"}],
            },
        )

    client = _client(handler)
    models = await client.list_models()

    assert models == [{"id": "test-model", "object": "model", "owned_by": "prometheus"}]
    await client.aclose()
