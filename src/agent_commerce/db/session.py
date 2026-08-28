"""Engine + sesión de SQLAlchemy, síncronos a propósito.

El dashboard es una herramienta de administración de bajo tráfico (un
puñado de personas probando protocolos de pago), no un servicio de alto
QPS: `Session` + `psycopg` (driver síncrono) es más simple y con menos
superficie de bugs de concurrencia que `asyncpg`, y FastAPI ya ejecuta
dependencias síncronas en un threadpool automáticamente -- no se pierde
nada práctico.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from agent_commerce.config import Settings, get_settings


@lru_cache
def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def build_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    settings = settings or get_settings()
    return sessionmaker(bind=get_engine(settings.database_url), autoflush=False, autocommit=False)


_default_session_factory: sessionmaker[Session] | None = None


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por request, cerrada al final."""
    global _default_session_factory
    if _default_session_factory is None:
        _default_session_factory = build_session_factory()
    db = _default_session_factory()
    try:
        yield db
    finally:
        db.close()
