"""AIBank modelo B desde el dashboard (RM-18): conectar la cuenta propia del
cliente con el flujo de `13-spec-modelos-a-y-b.md` §3 -- pedir permiso →
el titular decide (simulado: el banco real lo hace en su app) → activar el
mandato → pagar con AP2 sobre ese mandato, todo en caliente contra el mismo
`MockAIBank` con el que liquida el riel AIBank del vendedor."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agent_commerce.auth.bootstrap import create_admin
from agent_commerce.config import Mode, Settings, get_settings
from agent_commerce.dashboard.app import build_dashboard_app
from agent_commerce.db import models  # noqa: F401 -- registra las tablas en Base.metadata
from agent_commerce.db.base import Base
from agent_commerce.db.session import get_db

_TITULAR_ACCOUNT_ID = "acc_3f9e8d7c"


@pytest.fixture(autouse=True)
def _jwt_test_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENT_COMMERCE_JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
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

    app = build_dashboard_app(Settings(mode=Mode.MOCK))
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/auth/login", data={"username": "carlos", "password": "supersecret123"}
        )
        test_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        yield test_client
    engine.dispose()


def _request_consent(client: TestClient, **overrides: str) -> dict:
    body = {
        "max_per_operation_usd": "0.01",
        "max_total_usd": "0.05",
        "purpose": "Pagos del agente de investigación de Acme S.A.",
        **overrides,
    }
    response = client.post("/api/admin/aibank/consent-requests", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _connect_account(client: TestClient, **approval: str) -> dict:
    """Flujo completo hasta dejar el mandato activo como credencial."""
    request = _request_consent(client)
    approve = client.post(
        f"/api/admin/aibank/consent-requests/{request['consent_request_id']}/simulate-approval",
        json={"account_id": _TITULAR_ACCOUNT_ID, **approval},
    )
    assert approve.status_code == 200, approve.text
    activate = client.post(f"/api/admin/aibank/consent-requests/{request['consent_request_id']}/activate")
    assert activate.status_code == 200, activate.text
    return activate.json()


def _pay_with_ap2(client: TestClient):
    return client.post(
        "/api/test-call", json={"protocol": "ap2", "text": "Uno. Dos. Tres.", "max_sentences": 1}
    )


def test_consent_request_starts_pending_without_any_account(client: TestClient) -> None:
    """Doc 13 §3.1: la solicitud no lleva cuenta -- la elige el titular."""
    request = _request_consent(client)
    assert request["status"] == "pending"
    assert request["handoff_code"].startswith("csr_")
    assert request["account_id"] is None and request["mandate_id"] is None

    fetched = client.get(f"/api/admin/aibank/consent-requests/{request['consent_request_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "pending"


def test_consent_request_validates_limits_and_purpose(client: TestClient) -> None:
    base = {"max_per_operation_usd": "1", "max_total_usd": "5", "purpose": "x"}
    assert client.post(
        "/api/admin/aibank/consent-requests", json={**base, "max_per_operation_usd": "6"}
    ).status_code == 400
    assert client.post(
        "/api/admin/aibank/consent-requests", json={**base, "max_total_usd": "0"}
    ).status_code == 400
    empty_purpose = client.post("/api/admin/aibank/consent-requests", json={**base, "purpose": "   "})
    assert empty_purpose.status_code == 400
    assert empty_purpose.json()["detail"] == "malformed_request"


def test_unknown_consent_request_is_404(client: TestClient) -> None:
    assert client.get("/api/admin/aibank/consent-requests/no-existe").status_code == 404


def test_activating_before_approval_is_rejected(client: TestClient) -> None:
    """El mandato sale del banco: no se puede activar algo que el titular
    todavía no concedió."""
    request = _request_consent(client)
    response = client.post(f"/api/admin/aibank/consent-requests/{request['consent_request_id']}/activate")
    assert response.status_code == 409


def test_titular_cannot_raise_requested_limits(client: TestClient) -> None:
    request = _request_consent(client, max_total_usd="0.05")
    response = client.post(
        f"/api/admin/aibank/consent-requests/{request['consent_request_id']}/simulate-approval",
        json={"account_id": _TITULAR_ACCOUNT_ID, "max_total_usd": "1"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot_raise_requested_limits"


def test_rejected_consent_request_never_produces_a_mandate(client: TestClient) -> None:
    request = _request_consent(client)
    consent_request_id = request["consent_request_id"]
    rejected = client.post(f"/api/admin/aibank/consent-requests/{consent_request_id}/simulate-rejection")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"

    assert client.post(f"/api/admin/aibank/consent-requests/{consent_request_id}/activate").status_code == 409
    second_decision = client.post(
        f"/api/admin/aibank/consent-requests/{consent_request_id}/simulate-approval",
        json={"account_id": _TITULAR_ACCOUNT_ID},
    )
    assert second_decision.status_code == 409


def test_activating_switches_the_buyer_to_aibank_model_b(client: TestClient) -> None:
    settings = _connect_account(client)
    assert settings["backend"] == "aibank"
    assert settings["aibank_model"] == "mandate"
    assert settings["aibank_mandate_account_id"] == _TITULAR_ACCOUNT_ID

    mandate = client.get("/api/admin/aibank/mandate").json()
    assert mandate["configured"] and mandate["found"]
    assert mandate["status"] == "active"
    assert mandate["consumed_usd"] == "0" and mandate["remaining_usd"] == "0.05"


def test_titular_granting_less_than_requested_is_reflected_in_the_mandate(client: TestClient) -> None:
    _connect_account(client, max_total_usd="0.002")
    mandate = client.get("/api/admin/aibank/mandate").json()
    assert mandate["max_total_usd"] == "0.002"


def test_test_call_pays_over_the_customers_own_account(client: TestClient) -> None:
    _connect_account(client)

    response = _pay_with_ap2(client)
    assert response.status_code == 200, response.text
    receipt = response.json()["receipt"]
    assert receipt["network"] == "aibank:mock"
    assert receipt["payer"] == _TITULAR_ACCOUNT_ID
    assert receipt["wallet_backend"] == "aibank_mandate"

    mandate = client.get("/api/admin/aibank/mandate").json()
    assert mandate["consumed_usd"] == "0.001"


def test_payment_beyond_the_mandate_total_fails_with_limit_exceeded(client: TestClient) -> None:
    """Con saldo de sobra pero sin permiso: `mandate_limit_exceeded`, no
    `insufficient_funds` (doc 13 §5)."""
    _connect_account(client, max_total_usd="0.001")
    assert _pay_with_ap2(client).status_code == 200

    second = _pay_with_ap2(client)
    assert second.status_code == 502
    assert "mandate_limit_exceeded" in second.json()["detail"]


def test_payment_after_titular_revocation_fails(client: TestClient) -> None:
    _connect_account(client)
    revoked = client.post("/api/admin/aibank/mandate/simulate-revocation")
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"

    response = _pay_with_ap2(client)
    assert response.status_code == 502
    assert "mandate_revoked" in response.json()["detail"]


def test_model_b_without_a_connected_account_fails_clearly(client: TestClient) -> None:
    client.put("/api/admin/wallet-settings", json={"backend": "aibank", "aibank_model": "mandate"})
    response = _pay_with_ap2(client)
    assert response.status_code == 500
    assert "Cuenta propia" in response.json()["detail"]


def test_switching_back_to_omnibus_keeps_the_mandate_for_later(client: TestClient) -> None:
    """Volver al modelo A no pierde el mandato: se puede retomar el B sin
    pedirle permiso de nuevo al titular."""
    _connect_account(client)

    omnibus = client.put(
        "/api/admin/wallet-settings", json={"backend": "aibank", "aibank_model": "omnibus"}
    ).json()
    assert omnibus["aibank_model"] == "omnibus"
    assert omnibus["aibank_mandate_id"] is not None
    paid_omnibus = _pay_with_ap2(client).json()["receipt"]
    assert paid_omnibus["wallet_backend"] == "aibank"
    assert paid_omnibus["payer"] != _TITULAR_ACCOUNT_ID

    client.put("/api/admin/wallet-settings", json={"backend": "aibank", "aibank_model": "mandate"})
    assert _pay_with_ap2(client).json()["receipt"]["payer"] == _TITULAR_ACCOUNT_ID


def test_rejects_unknown_aibank_model(client: TestClient) -> None:
    response = client.put("/api/admin/wallet-settings", json={"backend": "aibank", "aibank_model": "otro"})
    assert response.status_code == 400


def test_mandate_endpoint_when_nothing_is_connected(client: TestClient) -> None:
    assert client.get("/api/admin/aibank/mandate").json() == {"configured": False}
