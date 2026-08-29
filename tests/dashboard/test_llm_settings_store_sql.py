from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from agent_commerce.dashboard.adapters.sql_llm_settings_store import SqlLlmSettingsStore


def test_get_returns_none_when_unconfigured(db_session: Session) -> None:
    store = SqlLlmSettingsStore(db_session)
    assert store.get() is None


def test_upsert_creates_then_get_returns_it(db_session: Session) -> None:
    store = SqlLlmSettingsStore(db_session)
    created = store.upsert(
        auth_base_url="http://auth.test",
        gateway_base_url="http://gateway.test",
        client_id="client-1",
        client_secret="secret-1",
        allowed_models=["model-a", "model-b"],
    )
    assert created.client_secret == "secret-1"

    fetched = store.get()
    assert fetched is not None
    assert fetched.auth_base_url == "http://auth.test"
    assert fetched.client_id == "client-1"
    assert fetched.allowed_models == ["model-a", "model-b"]


def test_upsert_without_secret_keeps_existing_secret(db_session: Session) -> None:
    store = SqlLlmSettingsStore(db_session)
    store.upsert(
        auth_base_url="http://auth.test",
        gateway_base_url="http://gateway.test",
        client_id="client-1",
        client_secret="secret-1",
        allowed_models=[],
    )

    updated = store.upsert(
        auth_base_url="http://auth2.test",
        gateway_base_url="http://gateway.test",
        client_id="client-1",
        client_secret=None,
        allowed_models=["model-a"],
    )

    assert updated.auth_base_url == "http://auth2.test"
    assert updated.client_secret == "secret-1"
    assert updated.allowed_models == ["model-a"]


def test_upsert_without_secret_on_empty_store_raises(db_session: Session) -> None:
    store = SqlLlmSettingsStore(db_session)
    with pytest.raises(ValueError, match="client_secret"):
        store.upsert(
            auth_base_url="http://auth.test",
            gateway_base_url="http://gateway.test",
            client_id="client-1",
            client_secret=None,
            allowed_models=[],
        )
