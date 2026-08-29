"""`WalletSettingsStore` en memoria -- para tests, sin Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

from ..ports import WalletSettings


class InMemoryWalletSettingsStore:
    def __init__(self) -> None:
        self._settings: WalletSettings | None = None

    def get(self) -> WalletSettings | None:
        return self._settings

    def upsert(
        self,
        *,
        backend: str,
        circle_api_key: str | None,
        circle_entity_secret: str | None,
        circle_wallet_id: str | None,
    ) -> WalletSettings:
        if backend == "circle":
            has_prior_api_key = self._settings is not None and self._settings.circle_api_key is not None
            has_prior_secret = self._settings is not None and self._settings.circle_entity_secret is not None
            if circle_api_key is None and not has_prior_api_key:
                raise ValueError("circle_api_key es obligatorio la primera vez que se configura")
            if circle_entity_secret is None and not has_prior_secret:
                raise ValueError("circle_entity_secret es obligatorio la primera vez que se configura")

        if circle_api_key is None and self._settings is not None:
            circle_api_key = self._settings.circle_api_key
        if circle_entity_secret is None and self._settings is not None:
            circle_entity_secret = self._settings.circle_entity_secret

        self._settings = WalletSettings(
            backend=backend,
            circle_api_key=circle_api_key,
            circle_entity_secret=circle_entity_secret,
            circle_wallet_id=circle_wallet_id,
            updated_at=datetime.now(UTC),
        )
        return self._settings
