"""Integración de punta a punta del dashboard: auth JWT + Postgres (SQLite en
tests) + los dos vendedores reales por protocolo, todo dentro de un mismo
proceso de test."""

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


@pytest.fixture(autouse=True)
def _jwt_test_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENT_COMMERCE_JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def dashboard_client() -> Iterator[TestClient]:
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

    settings = Settings(mode=Mode.MOCK)
    app = build_dashboard_app(settings)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    engine.dispose()


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login", data={"username": "carlos", "password": "supersecret123"}
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _auth_headers(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client)}"}


def test_protected_endpoint_requires_token(dashboard_client: TestClient) -> None:
    response = dashboard_client.get("/api/stats")
    assert response.status_code == 401


def test_stats_with_valid_token_starts_empty(dashboard_client: TestClient) -> None:
    response = dashboard_client.get("/api/stats", headers=_auth_headers(dashboard_client))
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "mock"
    assert body["total_calls"] == 0


def test_catalog_lists_seeded_entry(dashboard_client: TestClient) -> None:
    response = dashboard_client.get("/api/catalog", headers=_auth_headers(dashboard_client))
    assert response.status_code == 200
    ids = [entry["id"] for entry in response.json()]
    assert "text-summarizer" in ids


def test_create_and_delete_catalog_listing(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    payload = {
        "id": "my-test-service",
        "name": "My Test Service",
        "description": "desc",
        "method": "POST",
        "url": "http://example.com/x",
        "price_usd": "$0.01",
        "capability_tags": ["test"],
        "protocols": ["x402"],
    }
    created = dashboard_client.post("/api/catalog", json=payload, headers=headers)
    assert created.status_code == 201

    duplicate = dashboard_client.post("/api/catalog", json=payload, headers=headers)
    assert duplicate.status_code == 409

    deleted = dashboard_client.delete("/api/catalog/my-test-service", headers=headers)
    assert deleted.status_code == 200

    missing_again = dashboard_client.delete("/api/catalog/my-test-service", headers=headers)
    assert missing_again.status_code == 404


def test_update_catalog_listing(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    create_payload = {
        "id": "editable-service",
        "name": "Editable Service",
        "description": "desc",
        "method": "POST",
        "url": "http://example.com/x",
        "price_usd": "$0.01",
        "capability_tags": ["test"],
        "protocols": ["x402"],
        "provider_name": "acme",
    }
    created = dashboard_client.post("/api/catalog", json=create_payload, headers=headers)
    assert created.status_code == 201

    update_payload = {**create_payload, "name": "Renamed", "price_usd": "$0.02", "provider_name": "acme corp"}
    del update_payload["id"]
    updated = dashboard_client.put(
        "/api/catalog/editable-service", json=update_payload, headers=headers
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "Renamed"
    assert body["price_usd"] == "$0.02"
    assert body["provider_name"] == "acme corp"
    assert body["id"] == "editable-service"

    missing = dashboard_client.put(
        "/api/catalog/no-existe", json=update_payload, headers=headers
    )
    assert missing.status_code == 404


@pytest.mark.parametrize("protocol", ["x402", "ap2"])
def test_test_call_pays_and_records_ledger(dashboard_client: TestClient, protocol: str) -> None:
    headers = _auth_headers(dashboard_client)

    result = dashboard_client.post(
        "/api/test-call",
        json={"protocol": protocol, "text": "Frase uno. Frase dos. Frase tres.", "max_sentences": 1},
        headers=headers,
    )
    assert result.status_code == 200
    body = result.json()
    assert body["receipt"]["protocol"] == protocol
    assert "summary" in body["result"]

    ledger = dashboard_client.get("/api/ledger", headers=headers)
    assert ledger.status_code == 200
    entries = ledger.json()
    assert len(entries) == 1
    assert entries[0]["protocol"] == protocol
    assert entries[0]["status"] == "ok"

    stats = dashboard_client.get("/api/stats", headers=headers).json()
    assert stats["total_calls"] == 1
    assert stats["successful_calls"] == 1


def test_seller_preview_shows_402_without_payment(dashboard_client: TestClient) -> None:
    headers = _auth_headers(dashboard_client)
    response = dashboard_client.get("/api/seller-preview/x402", headers=headers)
    assert response.status_code == 200
    assert response.json()["status_code"] == 402
