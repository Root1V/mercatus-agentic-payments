"""`LlmSettingsStore` respaldado por Postgres. Fila única (`id=1`)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from agent_commerce.db.models import LlmSettingsModel

from ..ports import LlmSettings

_SINGLETON_ID = 1


def _to_settings(model: LlmSettingsModel) -> LlmSettings:
    return LlmSettings(
        auth_base_url=model.auth_base_url,
        gateway_base_url=model.gateway_base_url,
        client_id=model.client_id,
        client_secret=model.client_secret,
        allowed_models=list(model.allowed_models),
        updated_at=model.updated_at,
    )


class SqlLlmSettingsStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self) -> LlmSettings | None:
        model = self._db.get(LlmSettingsModel, _SINGLETON_ID)
        return _to_settings(model) if model is not None else None

    def upsert(
        self,
        *,
        auth_base_url: str,
        gateway_base_url: str,
        client_id: str,
        client_secret: str | None,
        allowed_models: list[str],
    ) -> LlmSettings:
        model = self._db.get(LlmSettingsModel, _SINGLETON_ID)
        if model is None:
            if client_secret is None:
                raise ValueError("client_secret es obligatorio la primera vez que se configura")
            model = LlmSettingsModel(id=_SINGLETON_ID, client_secret=client_secret)
            self._db.add(model)

        model.auth_base_url = auth_base_url
        model.gateway_base_url = gateway_base_url
        model.client_id = client_id
        if client_secret is not None:
            model.client_secret = client_secret
        model.allowed_models = list(allowed_models)

        self._db.commit()
        self._db.refresh(model)
        return _to_settings(model)
