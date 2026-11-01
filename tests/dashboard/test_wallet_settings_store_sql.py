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
        backend="local",
        circle_api_key=None,
        circle_entity_secret=None,
        circle_wallet_id=None,
        aibank_account_id=None,
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
        aibank_account_id=None,
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
        aibank_account_id=None,
    )

    updated = store.upsert(
        backend="circle",
        circle_api_key="key-2",
        circle_entity_secret=None,
        circle_wallet_id="wallet-2",
        aibank_account_id=None,
    )

    assert updated.circle_api_key == "key-2"
    assert updated.circle_wallet_id == "wallet-2"
    assert updated.circle_entity_secret == "a" * 64


def test_upsert_circle_without_secret_on_empty_store_raises(db_session: Session) -> None:
    store = SqlWalletSettingsStore(db_session)
    with pytest.raises(ValueError, match="circle_entity_secret"):
        store.upsert(
            backend="circle",
            circle_api_key="key-1",
            circle_entity_secret=None,
            circle_wallet_id="wallet-1",
            aibank_account_id=None,
        )


def test_switching_back_to_local_does_not_require_circle_secret(db_session: Session) -> None:
    """Cambiar a `local` no debería exigir un entity_secret que no aplica."""
    store = SqlWalletSettingsStore(db_session)
    store.upsert(
        backend="circle",
        circle_api_key="key-1",
        circle_entity_secret="a" * 64,
        circle_wallet_id="wallet-1",
        aibank_account_id=None,
    )

    updated = store.upsert(
        backend="local",
        circle_api_key=None,
        circle_entity_secret=None,
        circle_wallet_id=None,
        aibank_account_id=None,
    )
    assert updated.backend == "local"


def test_upsert_aibank_backend_needs_no_fields(db_session: Session) -> None:
    """A diferencia de Circle, AIBank no exige nada la primera vez: sin
    sub-cuenta, el dashboard usa una que abre solo en el banco. Y no hay API
    key que guardar -- en la API real se autentica la integración (AE-02)."""
    store = SqlWalletSettingsStore(db_session)
    created = store.upsert(
        backend="aibank",
        circle_api_key=None,
        circle_entity_secret=None,
        circle_wallet_id=None,
        aibank_account_id=None,
    )
    assert created.backend == "aibank"
    assert created.aibank_account_id is None


def test_upsert_aibank_with_account_then_get_returns_it(db_session: Session) -> None:
    store = SqlWalletSettingsStore(db_session)
    account_id = "acc_" + "1" * 32
    created = store.upsert(
        backend="aibank",
        circle_api_key=None,
        circle_entity_secret=None,
        circle_wallet_id=None,
        aibank_account_id=account_id,
    )
    assert created.aibank_account_id == account_id

    fetched = store.get()
    assert fetched is not None
    assert fetched.aibank_account_id == account_id


def test_set_aibank_mandate_on_empty_store_switches_to_model_b(db_session: Session) -> None:
    store = SqlWalletSettingsStore(db_session)
    saved = store.set_aibank_mandate(mandate_id="4a7b1c2d", account_id="acc_titular")
    assert saved.backend == "aibank"
    assert saved.aibank_model == "mandate"
    assert saved.aibank_mandate_id == "4a7b1c2d"
    assert saved.aibank_mandate_account_id == "acc_titular"


def test_upsert_keeps_mandate_and_model_when_not_given(db_session: Session) -> None:
    """Editar el resto de la config (o pasar a ómnibus y volver) no borra
    el mandato: retomarlo no obliga a pedirle permiso de nuevo al titular."""
    store = SqlWalletSettingsStore(db_session)
    store.set_aibank_mandate(mandate_id="4a7b1c2d", account_id="acc_titular")

    kept = store.upsert(
        backend="aibank",
        circle_api_key=None,
        circle_entity_secret=None,
        circle_wallet_id=None,
        aibank_account_id=None,
    )
    assert kept.aibank_model == "mandate"

    omnibus = store.upsert(
        backend="aibank",
        circle_api_key=None,
        circle_entity_secret=None,
        circle_wallet_id=None,
        aibank_account_id=None,
        aibank_model="omnibus",
    )
    assert omnibus.aibank_model == "omnibus"
    assert omnibus.aibank_mandate_id == "4a7b1c2d"
