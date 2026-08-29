"""`LlmSettingsStore` en memoria -- para tests, sin Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

from ..ports import LlmSettings


class InMemoryLlmSettingsStore:
    def __init__(self) -> None:
        self._settings: LlmSettings | None = None

    def get(self) -> LlmSettings | None:
        return self._settings

    def upsert(
        self,
        *,
        auth_base_url: str,
        gateway_base_url: str,
        client_id: str,
        client_secret: str | None,
        allowed_models: list[str],
    ) -> LlmSettings:
        if client_secret is None:
            if self._settings is None:
                raise ValueError("client_secret es obligatorio la primera vez que se configura")
            client_secret = self._settings.client_secret

        self._settings = LlmSettings(
            auth_base_url=auth_base_url,
            gateway_base_url=gateway_base_url,
            client_id=client_id,
            client_secret=client_secret,
            allowed_models=list(allowed_models),
            updated_at=datetime.now(UTC),
        )
        return self._settings
