from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agent_commerce.auth.bootstrap import AdminAlreadyExistsError, create_admin


def test_create_admin_then_login_succeeds(auth_client: TestClient, db_session: Session) -> None:
    create_admin(db_session, username="carlos", password="supersecret123")

    response = auth_client.post(
        "/api/auth/login", data={"username": "carlos", "password": "supersecret123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    me = auth_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == "carlos"


def test_login_with_wrong_password_is_rejected(auth_client: TestClient, db_session: Session) -> None:
    create_admin(db_session, username="carlos", password="supersecret123")

    response = auth_client.post(
        "/api/auth/login", data={"username": "carlos", "password": "wrong"}
    )
    assert response.status_code == 401


def test_login_with_unknown_user_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/auth/login", data={"username": "no-existe", "password": "whatever"}
    )
    assert response.status_code == 401


def test_me_without_token_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.get("/api/auth/me")
    assert response.status_code == 401


def test_creating_the_same_admin_twice_fails(db_session: Session) -> None:
    create_admin(db_session, username="carlos", password="supersecret123")
    try:
        create_admin(db_session, username="carlos", password="otra-clave")
        raise AssertionError("debería haber levantado AdminAlreadyExistsError")
    except AdminAlreadyExistsError:
        pass
