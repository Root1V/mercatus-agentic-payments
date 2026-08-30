"""Integración de `wallet_settings` (RM-19/RM-18): elegir el backend de
wallet del comprador (`local`/`circle`/`aibank`) desde el dashboard en
caliente, sin reiniciar el proceso -- salvo `aibank`, cuyo riel de AP2 queda
fijo desde que arranca el proceso (ver `dashboard_client_aibank_rail` más
abajo). El caso `circle` se prueba mockeando solo las llamadas de red del
SDK real de Circle (mismo patrón que `tests/payments/wallets/test_circle_wallet.py`),
nunca contra una cuenta real."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agent_commerce.auth.bootstrap import create_admin
from agent_commerce.config import Mode, Settings, SettlementRail, get_settings
from agent_commerce.dashboard.app import build_dashboard_app
from agent_commerce.db import models  # noqa: F401 -- registra las tablas en Base.metadata
from agent_commerce.db.base import Base
from agent_commerce.db.session import get_db

circle_dcw = pytest.importorskip("circle.web3.developer_controlled_wallets")
circle_utils = pytest.importorskip("circle.web3.utils")

# Cuenta local real usada SOLO para que el mock del SDK de Circle devuelva
# firmas EIP-712/EIP-191 criptográficamente válidas -- el facilitator x402
# (incluso en modo mock) verifica la firma de verdad, así que una firma
# inventada no alcanzaría para que el pago se liquide.
_MOCK_CIRCLE_ACCOUNT = Account.create()
_CIRCLE_ADDRESS = _MOCK_CIRCLE_ACCOUNT.address


@pytest.fixture(autouse=True)
def _jwt_test_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENT_COMMERCE_JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _build_dashboard_client(settings: Settings) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Iterator:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    admin_session = factory()
    create_admin(admin_session, username="carlos", password="supersecret123")
    admin_session.close()

    app = build_dashboard_app(settings)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    engine.dispose()


@pytest.fixture
def dashboard_client() -> Iterator[TestClient]:
    yield from _build_dashboard_client(Settings(mode=Mode.MOCK))


@pytest.fixture
def dashboard_client_aibank_rail() -> Iterator[TestClient]:
    """Dashboard arrancado con `ap2_settlement=aibank` -- el riel de AP2
    queda fijo desde que se construye la app (ver comentario en
    `build_dashboard_app`), así que probar el backend de wallet `aibank`
    necesita su propia instancia, distinta de `dashboard_client` (que arranca
    con el riel x402 por defecto)."""
    yield from _build_dashboard_client(Settings(mode=Mode.MOCK, ap2_settlement=SettlementRail.AIBANK))


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", data={"username": "carlos", "password": "supersecret123"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def mock_circle_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mockea únicamente las llamadas de red del SDK real de Circle -- los
    modelos pydantic (`EOAWallet`, `SignatureResponse`, etc.) son los reales
    del paquete instalado, igual que en `test_circle_wallet.py`."""

    def fake_get_wallet(*, id: str):
        wallet = circle_dcw.EOAWallet(
            id=id,
            address=_CIRCLE_ADDRESS,
            blockchain=circle_dcw.Blockchain.BASE_MINUS_SEPOLIA,
            create_date=datetime.now(UTC),
            update_date=datetime.now(UTC),
            custody_type=circle_dcw.CustodyType.DEVELOPER,
            state=circle_dcw.WalletState.LIVE,
            wallet_set_id="wallet-set-1",
            account_type=circle_dcw.AccountType.EOA,
        )
        wrapped = circle_dcw.WalletsDataWalletsInner(wallet)
        return circle_dcw.WalletResponse(data=circle_dcw.WalletResponseData(wallet=wrapped))

    def fake_sign_typed_data(self: object, request: object):
        # `request.data` es el mismo JSON EIP-712 (domain/types/primaryType/
        # message, con bytes ya como hex string) que `CircleWalletSigner`
        # arma para mandarle a Circle -- firmarlo de verdad con la cuenta
        # local simula "Circle firmó por nosotros" sin necesitar red real.
        full_message = json.loads(request.data)  # type: ignore[attr-defined]
        signed = _MOCK_CIRCLE_ACCOUNT.sign_typed_data(full_message=full_message)
        return circle_dcw.SignatureResponse(
            data=circle_dcw.SignatureResponseData(signature=signed.signature.to_0x_hex())
        )

    def fake_sign_message(self: object, request: object):
        raw = bytes.fromhex(request.message.removeprefix("0x"))  # type: ignore[attr-defined]
        signed = _MOCK_CIRCLE_ACCOUNT.sign_message(encode_defunct(primitive=raw))
        return circle_dcw.SignatureResponse(
            data=circle_dcw.SignatureResponseData(signature=signed.signature.to_0x_hex())
        )

    fake_wallets_api = type("FakeWalletsApi", (), {"get_wallet": staticmethod(fake_get_wallet)})()
    fake_signing_api = type(
        "FakeSigningApi", (), {"sign_typed_data": fake_sign_typed_data, "sign_message": fake_sign_message}
    )()

    monkeypatch.setattr(
        circle_utils, "init_developer_controlled_wallets_client", lambda **kwargs: object()
    )
    monkeypatch.setattr(circle_utils, "generate_entity_secret_ciphertext", lambda *a, **k: "fake-ciphertext")
    monkeypatch.setattr(circle_dcw, "WalletsApi", lambda client: fake_wallets_api)
    monkeypatch.setattr(circle_dcw, "SigningApi", lambda client: fake_signing_api)


def test_get_wallet_settings_defaults_to_env_backend(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.get("/api/admin/wallet-settings", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "local"
    assert body["has_circle_entity_secret"] is False


def test_put_wallet_settings_local(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.put(
        "/api/admin/wallet-settings",
        json={"backend": "local"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["backend"] == "local"

    get_response = dashboard_client.get("/api/admin/wallet-settings", headers=headers)
    assert get_response.json()["backend"] == "local"


def test_put_wallet_settings_circle_without_secret_first_time_fails(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.put(
        "/api/admin/wallet-settings",
        json={"backend": "circle", "circle_api_key": "k", "circle_wallet_id": "w"},
        headers=headers,
    )
    assert response.status_code == 400


def test_put_wallet_settings_rejects_unknown_backend(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.put(
        "/api/admin/wallet-settings", json={"backend": "mastercard"}, headers=headers
    )
    assert response.status_code == 400


def test_put_wallet_settings_never_returns_secret(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.put(
        "/api/admin/wallet-settings",
        json={
            "backend": "circle",
            "circle_api_key": "TEST_API_KEY:abc",
            "circle_entity_secret": "a" * 64,
            "circle_wallet_id": "wallet-1",
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert "circle_entity_secret" not in body
    assert "circle_api_key" not in body
    assert body["has_circle_entity_secret"] is True
    assert body["has_circle_api_key"] is True


def test_protocols_endpoint_degrades_gracefully_when_circle_misconfigured(
    dashboard_client: TestClient,
) -> None:
    headers = _auth_headers(dashboard_client)
    # backend=circle guardado sin wallet_id -- configuración incompleta a propósito.
    dashboard_client.put(
        "/api/admin/wallet-settings",
        json={"backend": "circle", "circle_api_key": "k", "circle_entity_secret": "a" * 64},
        headers=headers,
    )

    response = dashboard_client.get("/api/protocols", headers=headers)
    assert response.status_code == 200
    assert all(p["buyer_address"] is None for p in response.json())


def test_test_call_fails_clearly_when_circle_misconfigured(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    dashboard_client.put(
        "/api/admin/wallet-settings",
        json={"backend": "circle", "circle_api_key": "k", "circle_entity_secret": "a" * 64},
        headers=headers,
    )

    response = dashboard_client.post(
        "/api/test-call",
        json={"protocol": "x402", "text": "hola mundo", "max_sentences": 1},
        headers=headers,
    )
    assert response.status_code == 500
    assert "circle" in response.json()["detail"].lower()


@pytest.mark.usefixtures("mock_circle_sdk")
def test_test_call_pays_with_circle_backed_buyer(dashboard_client: TestClient) -> None:
    """El test central de RM-19: configurar `circle` desde el dashboard (sin
    tocar el entorno del proceso) y que un pago real de x402 en modo mock
    efectivamente firme con esa wallet -- se verifica que el `payer` del
    recibo sea la dirección devuelta por el SDK mockeado."""
    headers = _auth_headers(dashboard_client)
    dashboard_client.put(
        "/api/admin/wallet-settings",
        json={
            "backend": "circle",
            "circle_api_key": "TEST_API_KEY:abc",
            "circle_entity_secret": "a" * 64,
            "circle_wallet_id": "wallet-1",
        },
        headers=headers,
    )

    response = dashboard_client.post(
        "/api/test-call",
        json={"protocol": "x402", "text": "Frase uno. Frase dos. Frase tres.", "max_sentences": 1},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["receipt"]["payer"].lower() == _CIRCLE_ADDRESS.lower()
    assert body["receipt"]["wallet_backend"] == "circle"

    ledger = dashboard_client.get("/api/ledger", headers=headers).json()
    assert ledger[0]["payer"].lower() == _CIRCLE_ADDRESS.lower()


def test_test_call_receipt_reports_local_backend_by_default(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.post(
        "/api/test-call",
        json={"protocol": "x402", "text": "Frase uno. Frase dos. Frase tres.", "max_sentences": 1},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["receipt"]["wallet_backend"] == "local"


def test_put_wallet_settings_aibank_needs_no_fields(dashboard_client: TestClient) -> None:
    """A diferencia de Circle, AIBank no exige nada la primera vez -- se
    genera una cuenta efímera al vuelo si se deja vacío."""
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.put(
        "/api/admin/wallet-settings", json={"backend": "aibank"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "aibank"
    assert body["aibank_account_id"] is None
    assert body["has_aibank_api_key"] is False


def test_put_wallet_settings_aibank_never_returns_api_key(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.put(
        "/api/admin/wallet-settings",
        json={"backend": "aibank", "aibank_account_id": "cuenta-1", "aibank_api_key": "sk-secreta"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert "aibank_api_key" not in body
    assert body["aibank_account_id"] == "cuenta-1"
    assert body["has_aibank_api_key"] is True


def test_test_call_with_aibank_backend_fails_clearly_on_x402(dashboard_client: TestClient) -> None:
    """`aibank` solo tiene sentido con AP2 -- pedirlo sobre x402 tiene que
    fallar con un mensaje claro, no un error interno."""
    headers = _auth_headers(dashboard_client)
    dashboard_client.put("/api/admin/wallet-settings", json={"backend": "aibank"}, headers=headers)

    response = dashboard_client.post(
        "/api/test-call",
        json={"protocol": "x402", "text": "hola mundo", "max_sentences": 1},
        headers=headers,
    )
    assert response.status_code == 500
    assert "ap2" in response.json()["detail"].lower()


def test_test_call_with_aibank_backend_fails_clearly_when_dashboard_not_started_for_it(
    dashboard_client: TestClient,
) -> None:
    """`dashboard_client` (fixture por defecto) arranca con `ap2_settlement=x402`
    -- elegir el backend `aibank` de todos modos tiene que degradar con un
    mensaje claro (reiniciar con la env var), no una excepción cruda."""
    headers = _auth_headers(dashboard_client)
    dashboard_client.put("/api/admin/wallet-settings", json={"backend": "aibank"}, headers=headers)

    response = dashboard_client.post(
        "/api/test-call",
        json={"protocol": "ap2", "text": "hola mundo", "max_sentences": 1},
        headers=headers,
    )
    assert response.status_code == 500
    assert "ap2_settlement" in response.json()["detail"].lower()


def test_protocols_endpoint_shows_aibank_buyer_address_only_for_ap2(
    dashboard_client_aibank_rail: TestClient,
) -> None:
    headers = _auth_headers(dashboard_client_aibank_rail)
    dashboard_client_aibank_rail.put(
        "/api/admin/wallet-settings", json={"backend": "aibank"}, headers=headers
    )

    response = dashboard_client_aibank_rail.get("/api/protocols", headers=headers)
    assert response.status_code == 200
    by_name = {p["name"]: p for p in response.json()}
    assert by_name["x402"]["buyer_address"] is None
    assert by_name["ap2"]["buyer_address"] is not None


def test_test_call_with_ap2_fails_clearly_when_rail_is_aibank_but_backend_is_not(
    dashboard_client_aibank_rail: TestClient,
) -> None:
    """`dashboard_client_aibank_rail` arrancó con `ap2_settlement=aibank`,
    pero el backend de wallet del comprador sigue en 'local' (default) --
    la instancia de `AP2Protocol` ya montada solo acepta `AIBankCredential`,
    así que esto tiene que degradar con un mensaje claro, no un
    `AssertionError` crudo."""
    headers = _auth_headers(dashboard_client_aibank_rail)
    response = dashboard_client_aibank_rail.post(
        "/api/test-call",
        json={"protocol": "ap2", "text": "hola mundo", "max_sentences": 1},
        headers=headers,
    )
    assert response.status_code == 500
    assert "aibank" in response.json()["detail"].lower()


def test_test_call_pays_with_aibank_backed_buyer(dashboard_client_aibank_rail: TestClient) -> None:
    """El caso central de RM-18 en el dashboard: configurar `aibank` desde
    la UI (sin tocar el entorno del proceso) y que un pago real de AP2 en
    modo mock efectivamente liquide sobre AIBank -- se verifica que el
    `payer`/`red` del recibo reflejen ese riel."""
    headers = _auth_headers(dashboard_client_aibank_rail)
    dashboard_client_aibank_rail.put(
        "/api/admin/wallet-settings",
        json={"backend": "aibank", "aibank_account_id": "comprador-1"},
        headers=headers,
    )

    response = dashboard_client_aibank_rail.post(
        "/api/test-call",
        json={"protocol": "ap2", "text": "Frase uno. Frase dos. Frase tres.", "max_sentences": 1},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["receipt"]["payer"] == "comprador-1"
    assert body["receipt"]["network"] == "aibank:mock"
    assert body["receipt"]["wallet_backend"] == "aibank"

    ledger = dashboard_client_aibank_rail.get("/api/ledger", headers=headers).json()
    assert ledger[0]["payer"] == "comprador-1"
