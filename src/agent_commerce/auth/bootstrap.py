"""Creación del usuario admin -- SIN endpoint público de registro.

La única forma de crear un usuario es este helper, invocado desde
`agent-commerce create-admin` (ver `cli/main.py`). Reduce la superficie de
ataque: no hay altas abiertas en la API.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_commerce.db.models import UserModel

from .security import hash_password


class AdminAlreadyExistsError(Exception):
    pass


def create_admin(db: Session, *, username: str, password: str) -> UserModel:
    existing = db.execute(select(UserModel).where(UserModel.username == username)).scalar_one_or_none()
    if existing is not None:
        raise AdminAlreadyExistsError(f"Ya existe un usuario '{username}'")

    user = UserModel(username=username, hashed_password=hash_password(password), is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
