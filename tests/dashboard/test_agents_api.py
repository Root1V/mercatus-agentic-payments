"""Integración de punta a punta del playground de agentes (RM-14): agentes,
conversaciones y mensajes, incluyendo una corrida real de `AgentLoop` contra
un mock del auth-service/gateway de Prometheus levantado como servidor HTTP
real (mismo patrón que los vendedores x402/AP2 de `test_dashboard_app.py`) --
así se ejercita el `PrometheusLLMClient` real, no un doble en proceso.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from decimal import Decimal

import pytest
import uvicorn
from fastapi import FastAPI
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_uvicorn(app: FastAPI, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    return server


def _build_fake_prometheus_app(script: list[dict]) -> FastAPI:
    """Sirve `/oauth2/token`, `/v1/models` y `/v1/chat/completions` con
    respuestas fijas -- `script` es la secuencia de acciones ReAct
    (`{"thought", "action", "action_input"}`) que el "modelo" devuelve, una
    por cada llamada a `/v1/chat/completions`, en orden."""
    app = FastAPI()
    state = {"calls": 0}

    @app.post("/oauth2/token")
    async def token() -> dict:
        return {"access_token": "fake-token", "token_type": "bearer", "expires_in": 300, "scope": ""}

    @app.get("/v1/models")
    async def list_models() -> dict:
        return {"object": "list", "data": [{"id": "fake-model", "object": "model", "owned_by": "test"}]}

    @app.post("/v1/chat/completions")
    async def chat_completions() -> dict:
        action = script[state["calls"]]
        state["calls"] += 1
        return {"choices": [{"message": {"role": "assistant", "content": json.dumps(action)}}]}

    return app


@pytest.fixture(autouse=True)
def _jwt_test_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENT_COMMERCE_JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _build_client(*, script: list[dict] | None) -> Iterator[TestClient]:
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

    settings_kwargs: dict = {"mode": Mode.MOCK}
    if script is not None:
        fake_app = _build_fake_prometheus_app(script)
        port = _free_port()
        _start_uvicorn(fake_app, port)
        settings_kwargs.update(
            llm_auth_base_url=f"http://127.0.0.1:{port}",
            llm_gateway_base_url=f"http://127.0.0.1:{port}",
            llm_client_id="test-client",
            llm_client_secret="test-secret",
        )

    settings = Settings(**settings_kwargs)
    app = build_dashboard_app(settings)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    engine.dispose()


@pytest.fixture
def dashboard_client_no_llm() -> Iterator[TestClient]:
    yield from _build_client(script=None)


@pytest.fixture
def dashboard_client_with_llm() -> Iterator[TestClient]:
    final_answer = {
        "thought": "I know enough already",
        "action": "final_answer",
        "action_input": {"answer": "42"},
    }
    yield from _build_client(script=[final_answer])


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", data={"username": "carlos", "password": "supersecret123"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_llm_models_returns_500_when_not_configured(dashboard_client_no_llm: TestClient) -> None:
    headers = _auth_headers(dashboard_client_no_llm)
    response = dashboard_client_no_llm.get("/api/agents/llm-models", headers=headers)
    assert response.status_code == 500
    assert "LLM_CLIENT_ID" in response.json()["detail"]


def test_llm_models_proxies_gateway(dashboard_client_with_llm: TestClient) -> None:
    headers = _auth_headers(dashboard_client_with_llm)
    response = dashboard_client_with_llm.get("/api/agents/llm-models", headers=headers)
    assert response.status_code == 200
    assert response.json()["models"][0]["id"] == "fake-model"


def test_create_list_delete_agent(dashboard_client_no_llm: TestClient) -> None:
    headers = _auth_headers(dashboard_client_no_llm)
    payload = {
        "name": "Research Assistant",
        "instructions": "Be concise.",
        "llm_model": "fake-model",
        "protocol": "x402",
        "spend_limit_usd": "1.00",
    }
    created = dashboard_client_no_llm.post("/api/agents", json=payload, headers=headers)
    assert created.status_code == 201
    agent = created.json()
    assert agent["name"] == "Research Assistant"
    assert Decimal(agent["spend_limit_usd"]) == Decimal("1.00")

    listed = dashboard_client_no_llm.get("/api/agents", headers=headers)
    assert [a["id"] for a in listed.json()] == [agent["id"]]

    deleted = dashboard_client_no_llm.delete(f"/api/agents/{agent['id']}", headers=headers)
    assert deleted.status_code == 200
    assert dashboard_client_no_llm.get("/api/agents", headers=headers).json() == []


def test_create_agent_rejects_unknown_protocol(dashboard_client_no_llm: TestClient) -> None:
    headers = _auth_headers(dashboard_client_no_llm)
    payload = {"name": "A", "llm_model": "m", "protocol": "not-a-protocol"}
    response = dashboard_client_no_llm.post("/api/agents", json=payload, headers=headers)
    assert response.status_code == 400


def test_agents_are_isolated_per_user(dashboard_client_no_llm: TestClient) -> None:
    from agent_commerce.auth.dependencies import get_current_user
    from agent_commerce.db.models import UserModel

    headers = _auth_headers(dashboard_client_no_llm)
    created = dashboard_client_no_llm.post(
        "/api/agents",
        json={"name": "A", "llm_model": "m", "protocol": "x402"},
        headers=headers,
    )
    agent_id = created.json()["id"]

    other_user = UserModel(id=999, username="mallory", hashed_password="x", is_active=True)
    app = dashboard_client_no_llm.app
    app.dependency_overrides[get_current_user] = lambda: other_user  # type: ignore[attr-defined]
    try:
        # Otro usuario no puede ver las conversaciones de un agente que no es suyo.
        forbidden = dashboard_client_no_llm.get(f"/api/agents/{agent_id}/conversations", headers=headers)
        assert forbidden.status_code == 404
    finally:
        del app.dependency_overrides[get_current_user]  # type: ignore[attr-defined]


def test_conversation_and_message_flow_pays_and_records_ledger(
    dashboard_client_with_llm: TestClient,
) -> None:
    headers = _auth_headers(dashboard_client_with_llm)
    agent = dashboard_client_with_llm.post(
        "/api/agents",
        json={"name": "A", "llm_model": "fake-model", "protocol": "x402"},
        headers=headers,
    ).json()

    conversation = dashboard_client_with_llm.post(
        f"/api/agents/{agent['id']}/conversations", json={"title": "chat"}, headers=headers
    )
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]

    message = dashboard_client_with_llm.post(
        f"/api/agents/{agent['id']}/conversations/{conversation_id}/messages",
        json={"content": "What's the answer?"},
        headers=headers,
    )
    assert message.status_code == 201
    body = message.json()
    assert body["role"] == "agent"
    assert body["content"] == "42"
    assert Decimal(body["total_spent_usd"]) == Decimal(0)

    messages = dashboard_client_with_llm.get(
        f"/api/agents/{agent['id']}/conversations/{conversation_id}/messages", headers=headers
    ).json()
    assert [m["role"] for m in messages] == ["user", "agent"]

    ledger = dashboard_client_with_llm.get("/api/ledger", headers=headers).json()
    assert ledger == []  # sin call_service en la traza, no hay pago que registrar


@pytest.fixture
def dashboard_client_call_service() -> Iterator[TestClient]:
    script = [
        {
            "thought": "search first",
            "action": "search_catalog",
            "action_input": {"query": "summarize"},
        },
        {
            "thought": "now call it",
            "action": "call_service",
            "action_input": {
                "capability": "summarize",
                "payload": {"text": "Uno. Dos. Tres.", "max_sentences": 1},
            },
        },
        {"thought": "done", "action": "final_answer", "action_input": {"answer": "Summarized it."}},
    ]
    yield from _build_client(script=script)


@pytest.mark.parametrize("protocol", ["x402", "ap2"])
def test_call_service_action_pays_and_records_ledger(
    dashboard_client_call_service: TestClient, protocol: str
) -> None:
    client = dashboard_client_call_service
    headers = _auth_headers(client)
    agent = client.post(
        "/api/agents",
        json={"name": "A", "llm_model": "fake-model", "protocol": protocol},
        headers=headers,
    ).json()
    conversation = client.post(
        f"/api/agents/{agent['id']}/conversations", json={"title": "chat"}, headers=headers
    ).json()

    message = client.post(
        f"/api/agents/{agent['id']}/conversations/{conversation['id']}/messages",
        json={"content": "Summarize this for me"},
        headers=headers,
    )
    assert message.status_code == 201
    body = message.json()
    assert body["content"] == "Summarized it."
    assert body["trace"][1]["action"] == "call_service"
    assert Decimal(body["total_spent_usd"]) == Decimal("0.001")

    ledger = client.get("/api/ledger", headers=headers).json()
    assert len(ledger) == 1
    assert ledger[0]["protocol"] == protocol
    assert ledger[0]["status"] == "ok"
    assert Decimal(ledger[0]["amount_usd"]) == Decimal("0.001")


@pytest.fixture
def dashboard_client_invalid_json() -> Iterator[TestClient]:
    # `max_json_retries_per_turn` por defecto es 2 -> 3 respuestas inválidas seguidas agotan los reintentos.
    yield from _build_client(script=[{"not": "a valid action"}] * 3)


def test_agent_loop_error_is_persisted_as_agent_message_not_500(
    dashboard_client_invalid_json: TestClient,
) -> None:
    client = dashboard_client_invalid_json
    headers = _auth_headers(client)
    agent = client.post(
        "/api/agents",
        json={"name": "A", "llm_model": "fake-model", "protocol": "x402"},
        headers=headers,
    ).json()
    conversation = client.post(
        f"/api/agents/{agent['id']}/conversations", json={"title": "chat"}, headers=headers
    ).json()

    message = client.post(
        f"/api/agents/{agent['id']}/conversations/{conversation['id']}/messages",
        json={"content": "hi"},
        headers=headers,
    )
    assert message.status_code == 201
    assert "no pudo completar" in message.json()["content"]


def test_deleting_agent_cascades_conversations(dashboard_client_no_llm: TestClient) -> None:
    headers = _auth_headers(dashboard_client_no_llm)
    agent = dashboard_client_no_llm.post(
        "/api/agents", json={"name": "A", "llm_model": "m", "protocol": "x402"}, headers=headers
    ).json()
    dashboard_client_no_llm.post(
        f"/api/agents/{agent['id']}/conversations", json={"title": "c"}, headers=headers
    )

    dashboard_client_no_llm.delete(f"/api/agents/{agent['id']}", headers=headers)

    conversations_of_deleted_agent = dashboard_client_no_llm.get(
        f"/api/agents/{agent['id']}/conversations", headers=headers
    )
    assert conversations_of_deleted_agent.status_code == 404
