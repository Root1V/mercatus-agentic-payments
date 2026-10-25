"""`WalletSettingsStore` en memoria -- para tests, sin Postgres."""

from __future__ import annotations

from dataclasses import replace
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
        aibank_account_id: str | None,
        aibank_api_key: str | None,
        aibank_model: str | None = None,
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
        if aibank_api_key is None and self._settings is not None:
            aibank_api_key = self._settings.aibank_api_key
        if aibank_model is None and self._settings is not None:
            aibank_model = self._settings.aibank_model

        self._settings = WalletSettings(
            backend=backend,
            circle_api_key=circle_api_key,
            circle_entity_secret=circle_entity_secret,
            circle_wallet_id=circle_wallet_id,
            aibank_account_id=aibank_account_id,
            aibank_api_key=aibank_api_key,
            updated_at=datetime.now(UTC),
            aibank_model=aibank_model,
            aibank_mandate_id=self._settings.aibank_mandate_id if self._settings else None,
            aibank_mandate_account_id=self._settings.aibank_mandate_account_id if self._settings else None,
        )
        return self._settings

    def set_aibank_mandate(self, *, mandate_id: str, account_id: str) -> WalletSettings:
        base = self._settings or WalletSettings(
            backend="aibank",
            circle_api_key=None,
            circle_entity_secret=None,
            circle_wallet_id=None,
            aibank_account_id=None,
            aibank_api_key=None,
            updated_at=datetime.now(UTC),
        )
        self._settings = replace(
            base,
            backend="aibank",
            aibank_model="mandate",
            aibank_mandate_id=mandate_id,
            aibank_mandate_account_id=account_id,
            updated_at=datetime.now(UTC),
        )
        return self._settings
