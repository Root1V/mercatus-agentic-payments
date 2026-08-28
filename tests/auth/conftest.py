from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from agent_commerce.config import get_settings
from agent_commerce.db import models  # noqa: F401 -- registra las tablas en Base.metadata
from agent_commerce.db.base import Base
from agent_commerce.db.session import get_db


@pytest.fixture(autouse=True)
def _jwt_test_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Todas las pruebas de auth corren con un secreto JWT fijo, vía env vars
    (el mismo mecanismo que usaría un despliegue real), nunca hardcodeado en
    el código de producción."""
    monkeypatch.setenv("AGENT_COMMERCE_JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("AGENT_COMMERCE_JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("AGENT_COMMERCE_JWT_EXPIRES_MINUTES", "60")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_session() -> Iterator[Session]:
    """SQLite en memoria compartida (StaticPool: una sola conexión lógica,
    así todas las sesiones de la prueba ven las mismas tablas/filas)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def auth_client(db_session: Session) -> Iterator[TestClient]:
    from agent_commerce.auth.router import router as auth_router

    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app) as client:
        yield client
