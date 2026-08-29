"""`WalletSettingsStore` respaldado por Postgres. Fila única (`id=1`)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from agent_commerce.db.models import WalletSettingsModel

from ..ports import WalletSettings

_SINGLETON_ID = 1


def _to_settings(model: WalletSettingsModel) -> WalletSettings:
    return WalletSettings(
        backend=model.backend,
        circle_api_key=model.circle_api_key,
        circle_entity_secret=model.circle_entity_secret,
        circle_wallet_id=model.circle_wallet_id,
        updated_at=model.updated_at,
    )


class SqlWalletSettingsStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self) -> WalletSettings | None:
        model = self._db.get(WalletSettingsModel, _SINGLETON_ID)
        return _to_settings(model) if model is not None else None

    def upsert(
        self,
        *,
        backend: str,
        circle_api_key: str | None,
        circle_entity_secret: str | None,
        circle_wallet_id: str | None,
    ) -> WalletSettings:
        model = self._db.get(WalletSettingsModel, _SINGLETON_ID)
        if backend == "circle":
            has_prior_api_key = model is not None and model.circle_api_key is not None
            has_prior_secret = model is not None and model.circle_entity_secret is not None
            if circle_api_key is None and not has_prior_api_key:
                raise ValueError("circle_api_key es obligatorio la primera vez que se configura")
            if circle_entity_secret is None and not has_prior_secret:
                raise ValueError("circle_entity_secret es obligatorio la primera vez que se configura")

        if model is None:
            model = WalletSettingsModel(id=_SINGLETON_ID, backend=backend)
            self._db.add(model)

        model.backend = backend
        if circle_api_key is not None:
            model.circle_api_key = circle_api_key
        if circle_entity_secret is not None:
            model.circle_entity_secret = circle_entity_secret
        model.circle_wallet_id = circle_wallet_id

        self._db.commit()
        self._db.refresh(model)
        return _to_settings(model)
