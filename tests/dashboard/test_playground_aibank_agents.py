"""Cada agente del playground es SU PROPIO agente ante AIBank (contrato 1.1,
AE-10): su nombre -- el que ve el titular --, su clave, su sub-cuenta del
modelo A y su propio permiso del modelo B. Ningún agente paga con lo de otro."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agent_commerce.config import get_settings
from tests.dashboard.test_agents_api import _auth_headers, _build_client

_PAY_ONCE = [
    {"thought": "buscar", "action": "search_catalog", "action_input": {"query": "summarize"}},
    {
        "thought": "pagar",
        "action": "call_service",
        "action_input": {"capability": "summarize", "payload": {"text": "Uno. Dos. Tres.", "max_sentences": 1}},
    },
    {"thought": "listo", "action": "final_answer", "action_input": {"answer": "Hecho."}},
]


@pytest.fixture(autouse=True)
def _jwt_test_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENT_COMMERCE_JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Guion para hasta tres turnos de chat que pagan una vez cada uno.
    yield from _build_client(script=_PAY_ONCE * 3)


def _setup(client: TestClient, model: str) -> dict[str, str]:
    headers = _auth_headers(client)
    client.put("/api/admin/wallet-settings", json={"backend": "aibank", "aibank_model": model}, headers=headers)
    return headers


def _agent(client: TestClient, headers: dict[str, str], name: str) -> dict:
    return client.post(
        "/api/agents", json={"name": name, "llm_model": "fake-model", "protocol": "ap2"}, headers=headers
    ).json()


def _chat(client: TestClient, headers: dict[str, str], agent: dict):
    conversation = client.post(f"/api/agents/{agent['id']}/conversations", json={"title": "t"}, headers=headers).json()
    return client.post(
        f"/api/agents/{agent['id']}/conversations/{conversation['id']}/messages",
        json={"content": "Resumí esto"},
        headers=headers,
    )


def _payers(client: TestClient, headers: dict[str, str]) -> list[str]:
    return [entry["payer"] for entry in client.get("/api/ledger", headers=headers).json()]


def test_each_playground_agent_pays_from_its_own_account(client: TestClient) -> None:
    headers = _setup(client, "omnibus")
    viajes, compras = _agent(client, headers, "Agente de viajes"), _agent(client, headers, "Agente de compras")

    assert _chat(client, headers, viajes).status_code == 201
    assert _chat(client, headers, compras).status_code == 201

    payers = _payers(client, headers)
    dashboard_buyer = client.get("/api/admin/aibank/agent", headers=headers).json()["account_id"]
    assert len(payers) == 2 and len(set(payers)) == 2
    assert all(payer.startswith("acc_") and payer != dashboard_buyer for payer in payers)


async def test_the_holder_sees_each_agent_by_its_own_name(client: TestClient) -> None:
    headers = _setup(client, "omnibus")
    viajes = _agent(client, headers, "Agente de viajes")
    assert _chat(client, headers, viajes).status_code == 201

    request = client.post(
        f"/api/admin/aibank/consent-requests?agent_id={viajes['id']}",
        json={"max_per_operation_usd": "0.01", "max_total_usd": "0.05", "purpose": "Reservas"},
        headers=headers,
    ).json()
    bank = client.app.state.aibank  # type: ignore[attr-defined]
    consent = await bank.get_consent_request(request["consent_request_id"])
    assert (await bank.get_agent(consent.agent_id)).name == "Agente de viajes"


def test_model_b_needs_a_permission_for_that_agent(client: TestClient) -> None:
    headers = _setup(client, "mandate")
    viajes = _agent(client, headers, "Agente de viajes")

    blocked = _chat(client, headers, viajes)
    assert blocked.status_code == 500
    assert "Agente de viajes" in blocked.json()["detail"]

    request = client.post(
        f"/api/admin/aibank/consent-requests?agent_id={viajes['id']}",
        json={"max_per_operation_usd": "0.01", "max_total_usd": "0.05", "purpose": "Pagos del agente de viajes"},
        headers=headers,
    ).json()
    approved = client.post(
        f"/api/admin/aibank/consent-requests/{request['consent_request_id']}/simulate-approval", json={}, headers=headers
    )
    assert approved.status_code == 200, approved.text
    activated = client.post(
        f"/api/admin/aibank/consent-requests/{request['consent_request_id']}/activate?agent_id={viajes['id']}",
        headers=headers,
    )
    assert activated.status_code == 200, activated.text
    holder_account = activated.json()["aibank_mandate_account_id"]

    assert _chat(client, headers, viajes).status_code == 201
    assert _payers(client, headers) == [holder_account]
    mandate = client.get(f"/api/admin/aibank/mandate?agent_id={viajes['id']}", headers=headers).json()
    assert mandate["found"] and mandate["consumed_usd"] == "0.001"
    # El permiso es del agente, no del comprador del dashboard.
    assert client.get("/api/admin/wallet-settings", headers=headers).json()["aibank_mandate_id"] is None


def test_a_permission_requested_for_one_agent_cannot_be_given_to_another(client: TestClient) -> None:
    headers = _setup(client, "mandate")
    viajes, compras = _agent(client, headers, "Agente de viajes"), _agent(client, headers, "Agente de compras")
    request = client.post(
        f"/api/admin/aibank/consent-requests?agent_id={viajes['id']}",
        json={"max_per_operation_usd": "0.01", "max_total_usd": "0.05", "purpose": "Pagos del agente de viajes"},
        headers=headers,
    ).json()
    client.post(
        f"/api/admin/aibank/consent-requests/{request['consent_request_id']}/simulate-approval", json={}, headers=headers
    )
    stolen = client.post(
        f"/api/admin/aibank/consent-requests/{request['consent_request_id']}/activate?agent_id={compras['id']}",
        headers=headers,
    )
    assert stolen.status_code == 409


async def test_deleting_a_playground_agent_revokes_it_at_the_bank(client: TestClient) -> None:
    headers = _setup(client, "omnibus")
    viajes = _agent(client, headers, "Agente de viajes")
    assert _chat(client, headers, viajes).status_code == 201
    request = client.post(
        f"/api/admin/aibank/consent-requests?agent_id={viajes['id']}",
        json={"max_per_operation_usd": "0.01", "max_total_usd": "0.05", "purpose": "Reservas"},
        headers=headers,
    ).json()
    bank = client.app.state.aibank  # type: ignore[attr-defined]
    bank_agent_id = (await bank.get_consent_request(request["consent_request_id"])).agent_id

    assert client.delete(f"/api/agents/{viajes['id']}", headers=headers).status_code == 200
    assert (await bank.get_agent(bank_agent_id)).status == "revoked"
