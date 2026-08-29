from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from agent_commerce.dashboard.adapters.sql_wallet_settings_store import SqlWalletSettingsStore


def test_get_returns_none_when_unconfigured(db_session: Session) -> None:
    store = SqlWalletSettingsStore(db_session)
    assert store.get() is None


def test_upsert_local_backend_needs_no_circle_fields(db_session: Session) -> None:
    store = SqlWalletSettingsStore(db_session)
    created = store.upsert(
        backend="local", circle_api_key=None, circle_entity_secret=None, circle_wallet_id=None
    )
    assert created.backend == "local"

    fetched = store.get()
    assert fetched is not None
    assert fetched.backend == "local"


def test_upsert_circle_creates_then_get_returns_it(db_session: Session) -> None:
    store = SqlWalletSettingsStore(db_session)
    created = store.upsert(
        backend="circle",
        circle_api_key="TEST_API_KEY:abc",
        circle_entity_secret="a" * 64,
        circle_wallet_id="wallet-1",
    )
    assert created.circle_entity_secret == "a" * 64

    fetched = store.get()
    assert fetched is not None
    assert fetched.backend == "circle"
    assert fetched.circle_api_key == "TEST_API_KEY:abc"
    assert fetched.circle_wallet_id == "wallet-1"


def test_upsert_circle_without_secret_keeps_existing_secret(db_session: Session) -> None:
    store = SqlWalletSettingsStore(db_session)
    store.upsert(
        backend="circle",
        circle_api_key="key-1",
        circle_entity_secret="a" * 64,
        circle_wallet_id="wallet-1",
    )

    updated = store.upsert(
        backend="circle", circle_api_key="key-2", circle_entity_secret=None, circle_wallet_id="wallet-2"
    )

    assert updated.circle_api_key == "key-2"
    assert updated.circle_wallet_id == "wallet-2"
    assert updated.circle_entity_secret == "a" * 64


def test_upsert_circle_without_secret_on_empty_store_raises(db_session: Session) -> None:
    store = SqlWalletSettingsStore(db_session)
    with pytest.raises(ValueError, match="circle_entity_secret"):
        store.upsert(
            backend="circle", circle_api_key="key-1", circle_entity_secret=None, circle_wallet_id="wallet-1"
        )


def test_switching_back_to_local_does_not_require_circle_secret(db_session: Session) -> None:
    """Cambiar a `local` no debería exigir un entity_secret que no aplica."""
    store = SqlWalletSettingsStore(db_session)
    store.upsert(
        backend="circle",
        circle_api_key="key-1",
        circle_entity_secret="a" * 64,
        circle_wallet_id="wallet-1",
    )

    updated = store.upsert(backend="local", circle_api_key=None, circle_entity_secret=None, circle_wallet_id=None)
    assert updated.backend == "local"
