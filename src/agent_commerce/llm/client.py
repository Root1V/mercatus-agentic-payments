"""Cliente contra Prometheus (`edge-ai-inference`), la plataforma local de
inferencia LLM del usuario: OAuth2 `client_credentials` contra su
`auth-service` + `POST /v1/chat/completions` contra su `gateway`.

Contrato verificado leyendo el código fuente real de Prometheus (no
documentación de terceros ni suposiciones):

- `auth-service` (`POST {auth_base_url}/oauth2/token`, form-encoded, no
  JSON): responde `access_token`/`token_type`/`expires_in`/`scope`, o un
  error RFC 6749 §5.2 (`{"error": ..., "error_description": ...}`).
  `expires_in` depende del rol del client_id registrado (300s para el rol
  "app", que es el que usa esta integración) -- nunca se asume fijo, se lee
  de la respuesta en cada refresh.
- `gateway` (`POST {gateway_base_url}/v1/chat/completions`): pass-through
  case del backend llama.cpp cuando responde 2xx (shape OpenAI estándar);
  errores propios del gateway (auth, validación, rate limit, backend caído)
  usan RFC 9457 Problem Details (`application/problem+json`), no el shape
  `{"error": {...}}` de OpenAI.

Nota importante (ver docs/roadmap.md RM-11/RM-12): el `ChatCompletionRequest`
del gateway de Prometheus **no tiene campos `tools`/`tool_choice`** -- no hay
function-calling nativo, cualquier campo desconocido se descarta en
silencio. El tool-use del agente (RM-12) se implementa aparte, con un
contrato JSON en el propio prompt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


class LLMClientError(Exception):
    """Error base al hablar con Prometheus (auth-service o gateway)."""


class LLMAuthError(LLMClientError):
    """El auth-service rechazó el `client_credentials` grant (RFC 6749 §5.2)."""

    def __init__(self, error: str, error_description: str | None = None) -> None:
        self.error = error
        self.error_description = error_description
        super().__init__(f"{error}: {error_description}" if error_description else error)


class LLMGatewayError(LLMClientError):
    """El gateway devolvió un error RFC 9457 Problem Details."""

    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str | None,
        problem_type: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.problem_type = problem_type
        super().__init__(f"{status_code} {title}: {detail}" if detail else f"{status_code} {title}")


@dataclass
class _CachedToken:
    access_token: str
    expires_at_monotonic: float


class PrometheusLLMClient:
    """Habla con el `auth-service` (puerto 9000 por defecto) y el `gateway`
    (puerto 8000 por defecto -- choca con el del propio dashboard, así que
    en despliegues junto a `agent_commerce` conviene reconfigurar uno de los
    dos) de Prometheus. `auth_base_url`/`gateway_base_url`/`client_id`/
    `client_secret`/modelo son 100% configurables vía `Settings`, nunca
    hardcodeados aquí.
    """

    def __init__(
        self,
        *,
        auth_base_url: str,
        gateway_base_url: str,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 30.0,
        token_refresh_margin_seconds: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._auth_base_url = auth_base_url.rstrip("/")
        self._gateway_base_url = gateway_base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_margin = token_refresh_margin_seconds
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._token: _CachedToken | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get_access_token(self) -> str:
        cached = self._token
        if cached is not None and time.monotonic() < cached.expires_at_monotonic - self._refresh_margin:
            return cached.access_token

        response = await self._http.post(
            f"{self._auth_base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        body = response.json()
        if response.status_code != 200:
            raise LLMAuthError(
                error=body.get("error", "unknown_error"),
                error_description=body.get("error_description"),
            )

        token = _CachedToken(
            access_token=body["access_token"],
            expires_at_monotonic=time.monotonic() + float(body["expires_in"]),
        )
        self._token = token
        return token.access_token

    async def list_models(self) -> list[dict[str, Any]]:
        """`GET /v1/models` -- no requiere token (exento de auth en el gateway)."""
        response = await self._http.get(f"{self._gateway_base_url}/v1/models")
        _raise_for_gateway_error(response)
        result: list[dict[str, Any]] = response.json()["data"]
        return result

    async def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | str | None = None,
    ) -> dict[str, Any]:
        """`POST /v1/chat/completions` (sin streaming). `messages` usa el
        shape OpenAI estándar (`{"role": ..., "content": ...}`). El gateway
        de Prometheus descarta en silencio cualquier campo que no sea
        `model`/`messages`/`stream`/`max_tokens`/`temperature`/`top_p`/`stop`
        -- no tiene sentido exponer más parámetros aquí.
        """
        token = await self._get_access_token()
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stop is not None:
            payload["stop"] = stop

        response = await self._http.post(
            f"{self._gateway_base_url}/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        _raise_for_gateway_error(response)
        result: dict[str, Any] = response.json()
        return result


def _raise_for_gateway_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        problem = response.json()
    except ValueError:
        raise LLMGatewayError(
            status_code=response.status_code, title="unknown_error", detail=response.text
        ) from None
    raise LLMGatewayError(
        status_code=problem.get("status", response.status_code),
        title=problem.get("title", "error"),
        detail=problem.get("detail"),
        problem_type=problem.get("type"),
    )
