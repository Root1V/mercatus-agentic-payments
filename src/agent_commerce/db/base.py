"""Base declarativa de SQLAlchemy 2.0, compartida por todos los modelos ORM.

`naming_convention` explícito: sin esto, `alembic revision --autogenerate`
genera nombres de constraint/índice distintos según el backend (o incluso
entre corridas), lo que rompe migraciones futuras que necesiten referenciar
una constraint por nombre (p. ej. para borrarla). Con esto, el nombre es
determinístico siempre.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
